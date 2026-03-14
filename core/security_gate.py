"""
PHASE3_P3.4: Pre-trade security gate.

Extrait de src/trader_exec.py sans modification de logique.
Fonctions:
  - check_max_positions() -> (ok, msg)     : verifie MAX_OPEN_POSITIONS
  - check_antirug(mint) -> (ok, msg, skip) : verifie freeze/mint authority

Les deux sont fail-open: si erreur RPC/DB, ok=True (on ne bloque pas le trading).
"""
from __future__ import annotations
import os
from typing import Optional, Tuple


def _read_exposure_file() -> int:
    """
    Lit state/buy_exposure.json (écrit par trader_loop) et retourne
    le nombre de trades NON FERMÉS dans la fenêtre MAX_OPEN_MAX_AGE_H.

    Ce fichier contient une liste de timestamps Unix des BUY envoyés.
    Source de vérité indépendante de la DB (pas de dépendance à qty_token).
    Fail-safe: retourne -1 si lecture impossible.
    """
    import time as _t
    _max_age_h = float(os.getenv("MAX_OPEN_MAX_AGE_H", "48"))
    _exposure_path = os.path.join(
        os.getenv("HEARTBEAT_DIR", "state"), "buy_exposure.json"
    )
    try:
        import json as _ej
        with open(_exposure_path, "r", encoding="utf-8") as _f:
            _data = _ej.load(_f)
        if not isinstance(_data, list):
            return -1
        _now = _t.time()
        _cutoff = _now - (_max_age_h * 3600)
        _count = sum(1 for ts in _data if isinstance(ts, (int, float)) and ts >= _cutoff)
        return _count
    except FileNotFoundError:
        return -1
    except Exception:
        return -1


def check_max_positions() -> Tuple[bool, str]:
    """
    Vérifie le plafond d'exposition via 2 sources (la plus haute gagne):

    1. PRIMAIRE: buy_exposure.json — trades récents écrits par trader_loop
       Fiable immédiatement après un BUY (pas de dépendance à qty_token).

    2. SECONDAIRE: DB positions — OPEN + qty_token > 0 + entry_ts récent
       Rattrape les positions hydratées qui n'auraient pas de fichier.

    Le compteur final = max(fichier, DB) pour ne jamais sous-estimer l'exposition.

    Fail-open: si les deux sources échouent, retourne (True, ...).

    Env vars:
      MAX_OPEN_POSITIONS   : limite (default 0 = disabled)
      MAX_OPEN_MAX_AGE_H   : fenêtre en heures (default 48h)
    """
    _max_open = int(os.getenv("MAX_OPEN_POSITIONS", "0"))
    if _max_open <= 0:
        return True, ""

    _max_age_h = float(os.getenv("MAX_OPEN_MAX_AGE_H", "48"))

    # --- Source 1: fichier buy_exposure.json ---
    _file_count = _read_exposure_file()

    # --- Source 2: DB (secondaire) ---
    _db_count = 0
    _db_total = 0
    _db_ok = False
    try:
        import sqlite3
        import time as _mop_time
        _mop_db = os.getenv(
            "TRADES_DB_PATH", os.getenv("DB_PATH", "state/trades.sqlite")
        )
        _mop_con = sqlite3.connect(_mop_db, timeout=5)

        _cols_info = _mop_con.execute("PRAGMA table_info(positions)").fetchall()
        _col_names = {row[1] for row in _cols_info}

        _db_total = _mop_con.execute(
            "SELECT COUNT(*) FROM positions WHERE status LIKE 'OPEN%'"
        ).fetchone()[0]

        # DB: OPEN + qty_token > 0 + récent
        _where = "status LIKE 'OPEN%'"
        _params: list = []
        if "qty_token" in _col_names:
            _where += " AND COALESCE(qty_token, 0) > 0"
        if "entry_ts" in _col_names and _max_age_h > 0:
            _cutoff_ts = int(_mop_time.time()) - int(_max_age_h * 3600)
            _where += " AND COALESCE(entry_ts, 0) >= ?"
            _params.append(_cutoff_ts)
        _db_count = _mop_con.execute(
            f"SELECT COUNT(*) FROM positions WHERE {_where}", _params
        ).fetchone()[0]
        _mop_con.close()
        _db_ok = True
    except Exception as _db_e:
        print(f"⚠️ MAX_OPEN DB read failed (non-fatal): {_db_e}", flush=True)

    # --- Compteur final: max(fichier, DB) ---
    if _file_count >= 0:
        _active = max(_file_count, _db_count)
        _source = f"file={_file_count},db={_db_count}"
    elif _db_ok:
        _active = _db_count
        _source = f"db={_db_count}(file unavailable)"
    else:
        # Aucune source fiable → fail-open
        print("⚠️ MAX_OPEN_POSITIONS: no reliable source (fail-open)", flush=True)
        return True, ""

    _ignored = _db_total - _active if _db_total > _active else 0
    _detail = f" [{_source}, total_open={_db_total}]"

    if _active >= _max_open:
        msg = f"🛑 MAX_OPEN_POSITIONS: {_active}/{_max_open} active{_detail} → skip BUY"
        print(msg, flush=True)
        return False, msg
    else:
        print(
            f"📊 MAX_OPEN_POSITIONS: {_active}/{_max_open} active{_detail} (OK)", flush=True
        )
        return True, ""


def check_antirug(output_mint: str) -> Tuple[bool, str, Optional[str]]:
    """
    Verifie freeze_authority et mint_authority du mint on-chain.
    Retourne (ok, msg, skip_reason):
      - ok=True  : continue trading
      - ok=False : BLOCK (freeze_authority detecte)
      - skip_reason : si non-None, le caller doit ajouter le mint au skip list

    Fail-open: si erreur RPC, ok=True.
    Controllable via ANTIRUG_ENABLED env var.
    """
    _ANTIRUG_ENABLED = os.getenv("ANTIRUG_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not _ANTIRUG_ENABLED:
        return True, "", None

    try:
        import requests as _ar_rq

        _ar_rpc = os.getenv(
            "RPC_HTTP",
            os.getenv(
                "SOLANA_RPC_HTTP",
                os.getenv(
                    "SOLANA_RPC_URL",
                    os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com"),
                ),
            ),
        )
        _ar_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [str(output_mint), {"encoding": "jsonParsed"}],
        }
        _ar_resp = _ar_rq.post(_ar_rpc, json=_ar_payload, timeout=8)
        if _ar_resp.status_code == 200:
            _ar_j = _ar_resp.json()
            _ar_val = ((_ar_j or {}).get("result") or {}).get("value")
            if _ar_val:
                _ar_parsed = (
                    ((_ar_val.get("data") or {}).get("parsed") or {}).get("info") or {}
                )
                _ar_freeze = _ar_parsed.get("freezeAuthority")
                _ar_mint = _ar_parsed.get("mintAuthority")
                if _ar_freeze is not None:
                    msg = f"🛑 ANTIRUG BLOCK: freeze_authority={_ar_freeze} → mint {output_mint} REJETÉ (rug risk)"
                    print(msg, flush=True)
                    return False, msg, "antirug_freeze"
                if _ar_mint is not None:
                    print(
                        f"⚠️ ANTIRUG WARN: mint_authority={_ar_mint} → mint {output_mint} (inflation risk, trade autorisé)",
                        flush=True,
                    )
            else:
                print(
                    f"⚠️ ANTIRUG: mint {output_mint} non trouvé on-chain (fail-open, continue)",
                    flush=True,
                )
        else:
            print(
                f"⚠️ ANTIRUG: RPC status={_ar_resp.status_code} (fail-open, continue)",
                flush=True,
            )
    except Exception as _ar_e:
        print(
            f"⚠️ ANTIRUG: check failed err={_ar_e} (fail-open, continue)", flush=True
        )
    return True, "", None
