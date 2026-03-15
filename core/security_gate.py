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
    le nombre TOTAL d'entrées dans le fichier.

    Le fichier est déjà nettoyé par le writer (purge > 48h à chaque écriture),
    donc on compte simplement toutes les entrées sans filtre supplémentaire.
    Ceci évite le bug où MAX_OPEN_MAX_AGE_H=0 causait un cutoff = now → count=0.

    Source de vérité indépendante de la DB (pas de dépendance à qty_token).
    Fail-safe: retourne -1 si lecture impossible.
    """
    _exposure_path = os.path.join(
        os.getenv("HEARTBEAT_DIR", "state"), "buy_exposure.json"
    )
    try:
        import json as _ej
        with open(_exposure_path, "r", encoding="utf-8") as _f:
            _data = _ej.load(_f)
        if not isinstance(_data, list):
            print(f"⚠️ EXPOSURE_READ: invalid format in {_exposure_path}", flush=True)
            return -1
        # Compter toutes les entrées valides (le writer purge déjà les vieilles)
        _count = sum(1 for ts in _data if isinstance(ts, (int, float)))
        print(f"📊 EXPOSURE_READ: {_exposure_path} → {_count} entries", flush=True)
        return _count
    except FileNotFoundError:
        print(f"📊 EXPOSURE_READ: {_exposure_path} not found (first run?)", flush=True)
        return -1
    except Exception as _e:
        print(f"⚠️ EXPOSURE_READ: error reading {_exposure_path}: {_e}", flush=True)
        return -1


def _count_recent_closes() -> int:
    """
    Compte les positions FERMÉES récemment (close_ts dans la fenêtre 48h).
    Utilisé pour soustraire du compteur d'exposition fichier.

    Sans cela, buy_exposure.json ne fait qu'augmenter et le bot
    s'auto-bloque après MAX_OPEN achats même si tout est vendu.

    Fail-safe: retourne 0 si lecture impossible.
    """
    try:
        import sqlite3
        import time as _ct
        _max_age_h = max(float(os.getenv("MAX_OPEN_MAX_AGE_H", "48")), 1.0)
        _mop_db = os.getenv(
            "TRADES_DB_PATH", os.getenv("DB_PATH", "state/trades.sqlite")
        )
        _con = sqlite3.connect(_mop_db, timeout=5)

        _cols_info = _con.execute("PRAGMA table_info(positions)").fetchall()
        _col_names = {row[1] for row in _cols_info}

        if "close_ts" not in _col_names:
            _con.close()
            return 0

        _cutoff = int(_ct.time()) - int(_max_age_h * 3600)
        _closed = _con.execute(
            "SELECT COUNT(*) FROM positions WHERE status NOT LIKE 'OPEN%' AND COALESCE(close_ts, 0) >= ?",
            (_cutoff,)
        ).fetchone()[0]
        _con.close()
        return _closed
    except Exception:
        return 0


def check_max_positions() -> Tuple[bool, str]:
    """
    Vérifie le plafond d'exposition NETTE:

    exposition_nette = achats_récents (fichier) - ventes_récentes (DB)

    Sources:
      1. buy_exposure.json — tous les BUY rc=2 (timestamps)
      2. DB positions — positions CLOSED avec close_ts récent

    Le calcul: net = file_count - closed_count (plancher à 0).
    Ceci résout le bug où l'exposition ne descendait JAMAIS quand on vendait,
    bloquant le bot après MAX_OPEN achats même si tout était vendu.

    Fail-open: si les sources échouent, retourne (True, ...).

    Env vars:
      MAX_OPEN_POSITIONS   : limite (default 0 = disabled)
      MAX_OPEN_MAX_AGE_H   : fenêtre en heures (default 48h)
    """
    _max_open = int(os.getenv("MAX_OPEN_POSITIONS", "0"))
    if _max_open <= 0:
        return True, ""

    # --- Source 1: fichier buy_exposure.json (achats bruts) ---
    _file_count = _read_exposure_file()

    # --- Source 2: positions fermées récemment (à soustraire) ---
    _closed_count = _count_recent_closes()

    # --- Exposition nette ---
    if _file_count >= 0:
        _net = max(0, _file_count - _closed_count)
        _source = f"file={_file_count}-closed={_closed_count}=net={_net}"
    else:
        # Fichier indisponible → fallback DB brut
        _net = 0
        _db_ok = False
        try:
            import sqlite3
            import time as _mop_time
            _max_age_h = max(float(os.getenv("MAX_OPEN_MAX_AGE_H", "48")), 1.0)
            _mop_db = os.getenv(
                "TRADES_DB_PATH", os.getenv("DB_PATH", "state/trades.sqlite")
            )
            _mop_con = sqlite3.connect(_mop_db, timeout=5)
            _cols_info = _mop_con.execute("PRAGMA table_info(positions)").fetchall()
            _col_names = {row[1] for row in _cols_info}
            _where = "status LIKE 'OPEN%'"
            _params: list = []
            if "entry_ts" in _col_names and _max_age_h > 0:
                _cutoff_ts = int(_mop_time.time()) - int(_max_age_h * 3600)
                _where += " AND COALESCE(entry_ts, 0) >= ?"
                _params.append(_cutoff_ts)
            _net = _mop_con.execute(
                f"SELECT COUNT(*) FROM positions WHERE {_where}", _params
            ).fetchone()[0]
            _mop_con.close()
            _db_ok = True
            _source = f"db_fallback={_net}(file unavailable)"
        except Exception as _db_e:
            print(f"⚠️ MAX_OPEN_POSITIONS: no reliable source (fail-open): {_db_e}", flush=True)
            return True, ""

    _detail = f" [{_source}]"

    if _net >= _max_open:
        msg = f"🛑 MAX_OPEN_POSITIONS: {_net}/{_max_open} net{_detail} → skip BUY"
        print(msg, flush=True)
        return False, msg
    else:
        print(
            f"📊 MAX_OPEN_POSITIONS: {_net}/{_max_open} net{_detail} (OK)", flush=True
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
