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


def check_max_positions() -> Tuple[bool, str]:
    """
    Verifie le nombre de positions ouvertes ACTIVES (ignore poussière/historique).
    Retourne (True, msg) si OK, (False, msg) si trop de positions.
    Fail-open: si erreur, retourne (True, ...).

    Env vars:
      MAX_OPEN_POSITIONS       : limite (default 0 = disabled)
      MAX_OPEN_MIN_SIZE_SOL    : seuil min pour compter une position (default 0.005)
    """
    _max_open = int(os.getenv("MAX_OPEN_POSITIONS", "0"))
    if _max_open <= 0:
        return True, ""

    _min_size = float(os.getenv("MAX_OPEN_MIN_SIZE_SOL", "0.005"))

    try:
        import sqlite3
        _mop_db = os.getenv(
            "TRADES_DB_PATH", os.getenv("DB_PATH", "state/trades.sqlite")
        )
        _mop_con = sqlite3.connect(_mop_db, timeout=5)

        # Détection dynamique des colonnes disponibles
        _cols_info = _mop_con.execute("PRAGMA table_info(positions)").fetchall()
        _col_names = {row[1] for row in _cols_info}

        # Comptage intelligent: ignore les positions poussière (size_sol < seuil)
        if "size_sol" in _col_names and _min_size > 0:
            _mop_count = _mop_con.execute(
                "SELECT COUNT(*) FROM positions WHERE status LIKE 'OPEN%' AND COALESCE(size_sol, 0) >= ?",
                (_min_size,)
            ).fetchone()[0]
            _mop_total = _mop_con.execute(
                "SELECT COUNT(*) FROM positions WHERE status LIKE 'OPEN%'"
            ).fetchone()[0]
            _dust_count = _mop_total - _mop_count
        else:
            _mop_count = _mop_con.execute(
                "SELECT COUNT(*) FROM positions WHERE status LIKE 'OPEN%'"
            ).fetchone()[0]
            _mop_total = _mop_count
            _dust_count = 0

        _mop_con.close()

        _dust_info = f" (ignored {_dust_count} dust<{_min_size}SOL)" if _dust_count > 0 else ""
        if _mop_count >= _max_open:
            msg = f"🛑 MAX_OPEN_POSITIONS: {_mop_count}/{_max_open} active positions{_dust_info} → skip BUY"
            print(msg, flush=True)
            return False, msg
        else:
            print(
                f"📊 MAX_OPEN_POSITIONS: {_mop_count}/{_max_open} active{_dust_info} (OK)", flush=True
            )
            return True, ""
    except Exception as _mop_e:
        print(
            f"⚠️ MAX_OPEN_POSITIONS check failed (fail-open): {_mop_e}", flush=True
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
