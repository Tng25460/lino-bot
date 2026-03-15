"""
PHASE3_P3.4: Pre-trade security gate.

Extrait de src/trader_exec.py sans modification de logique.
Fonctions:
  - check_max_positions() -> (ok, msg)     : verifie MAX_OPEN_POSITIONS
  - check_antirug(mint) -> (ok, msg, skip) : verifie freeze/mint authority

Les deux sont fail-open: si erreur RPC/DB, ok=True (on ne bloque pas le trading).

EXPOSURE_V3: registre actif par mint (plus de soustraction globale).
  - active_exposure.json = {mint: buy_ts, ...}
  - Entrée ajoutée par trader_loop à rc=2
  - Entrée retirée quand la position est confirmée CLOSED dans la DB
  - Fallback DB OPEN count si fichier indisponible
"""
from __future__ import annotations
import os
from typing import Optional, Tuple


# ============================================================
# EXPOSURE_V3: registre actif par mint
# ============================================================

_ACTIVE_EXPOSURE_FILE = os.path.join(
    os.getenv("HEARTBEAT_DIR", "state"), "active_exposure.json"
)


def _load_active_exposure() -> dict:
    """Charge le registre actif {mint: buy_ts, ...}. Fail-safe: retourne {}."""
    try:
        import json as _j
        with open(_ACTIVE_EXPOSURE_FILE, "r", encoding="utf-8") as _f:
            _data = _j.load(_f)
        if isinstance(_data, dict):
            return _data
        return {}
    except FileNotFoundError:
        return {}
    except Exception as _e:
        print(f"⚠️ EXPOSURE_V3: load error: {_e}", flush=True)
        return {}


def _save_active_exposure(data: dict) -> None:
    """Sauvegarde atomique du registre actif."""
    try:
        import json as _j
        import tempfile as _tf
        _d = os.path.dirname(_ACTIVE_EXPOSURE_FILE) or "."
        os.makedirs(_d, exist_ok=True)
        _fd, _tmp = _tf.mkstemp(prefix=".active_exp_", suffix=".json", dir=_d)
        try:
            with os.fdopen(_fd, "w", encoding="utf-8") as _wf:
                _j.dump(data, _wf, ensure_ascii=False, separators=(",", ":"))
            os.replace(_tmp, _ACTIVE_EXPOSURE_FILE)
        finally:
            try:
                if os.path.exists(_tmp):
                    os.unlink(_tmp)
            except Exception:
                pass
    except Exception as _e:
        print(f"⚠️ EXPOSURE_V3: save error: {_e}", flush=True)


def exposure_add(mint: str) -> None:
    """Enregistre un achat actif. Appelé par trader_loop quand rc=2."""
    try:
        import time as _t
        _m = str(mint).strip()
        if not _m:
            return
        _data = _load_active_exposure()
        _data[_m] = int(_t.time())
        _save_active_exposure(_data)
        print(f"📊 EXPOSURE_V3: add mint={_m[:12]}… (active={len(_data)})", flush=True)
    except Exception as _e:
        print(f"⚠️ EXPOSURE_V3: add failed: {_e}", flush=True)


def exposure_remove(mint: str) -> None:
    """Retire un mint du registre actif. Appelé quand position confirmée CLOSED."""
    try:
        _m = str(mint).strip()
        if not _m:
            return
        _data = _load_active_exposure()
        if _m in _data:
            del _data[_m]
            _save_active_exposure(_data)
            print(f"📊 EXPOSURE_V3: remove mint={_m[:12]}… (active={len(_data)})", flush=True)
    except Exception as _e:
        print(f"⚠️ EXPOSURE_V3: remove failed: {_e}", flush=True)


def _reconcile_exposure() -> int:
    """
    Réconcilie le registre actif avec la DB.
    Retire les mints dont la position est confirmée CLOSED dans la DB.
    Retire aussi les mints > 48h sans position OPEN (cleanup sécurité).
    Retourne le nombre d'entrées actives après réconciliation.
    """
    try:
        import sqlite3
        import time as _t

        _data = _load_active_exposure()
        if not _data:
            return 0

        _mop_db = os.getenv(
            "TRADES_DB_PATH", os.getenv("DB_PATH", "state/trades.sqlite")
        )
        _now = int(_t.time())
        _max_stale_h = max(float(os.getenv("MAX_OPEN_MAX_AGE_H", "48")), 1.0)
        _stale_cutoff = _now - int(_max_stale_h * 3600)

        _to_remove = []
        try:
            _con = sqlite3.connect(_mop_db, timeout=5)
            _cols_info = _con.execute("PRAGMA table_info(positions)").fetchall()
            _col_names = {row[1] for row in _cols_info}
            _has_close_ts = "close_ts" in _col_names

            for _mint, _buy_ts in list(_data.items()):
                try:
                    _buy_ts_int = int(_buy_ts)
                except (TypeError, ValueError):
                    _buy_ts_int = 0

                # Vérifier si la position est CLOSED dans la DB
                try:
                    _row = _con.execute(
                        "SELECT status FROM positions WHERE mint = ? ORDER BY ROWID DESC LIMIT 1",
                        (_mint,)
                    ).fetchone()
                    if _row:
                        _status = str(_row[0] or "")
                        if not _status.startswith("OPEN"):
                            # Position confirmée CLOSED → retirer
                            _to_remove.append(_mint)
                            continue
                except Exception:
                    pass

                # Cleanup sécurité: entrée > 48h sans position OPEN → probablement orpheline
                if _buy_ts_int > 0 and _buy_ts_int < _stale_cutoff:
                    _to_remove.append(_mint)

            _con.close()
        except Exception as _db_e:
            # DB indisponible → pas de réconciliation, garder l'existant
            print(f"⚠️ EXPOSURE_V3: reconcile DB error (keep existing): {_db_e}", flush=True)
            return len(_data)

        if _to_remove:
            for _m in _to_remove:
                _data.pop(_m, None)
            _save_active_exposure(_data)
            print(f"📊 EXPOSURE_V3: reconciled, removed {len(_to_remove)} closed/stale (active={len(_data)})", flush=True)

        return len(_data)

    except Exception as _e:
        print(f"⚠️ EXPOSURE_V3: reconcile failed (fail-open): {_e}", flush=True)
        return -1


def _count_db_open() -> int:
    """Fallback: compte les positions OPEN dans la DB. Schema-safe."""
    try:
        import sqlite3
        import time as _t
        _mop_db = os.getenv(
            "TRADES_DB_PATH", os.getenv("DB_PATH", "state/trades.sqlite")
        )
        _con = sqlite3.connect(_mop_db, timeout=5)
        _count = _con.execute(
            "SELECT COUNT(*) FROM positions WHERE status LIKE 'OPEN%'"
        ).fetchone()[0]
        _con.close()
        return _count
    except Exception:
        return -1


def check_max_positions() -> Tuple[bool, str]:
    """
    Vérifie le plafond d'exposition ACTIVE (EXPOSURE_V3).

    Source de vérité: active_exposure.json (registre par mint).
    Réconcilié avec la DB à chaque appel (retire les CLOSED).
    Fallback: DB OPEN count si fichier indisponible.

    Fail-open: si toutes les sources échouent, retourne (True, ...).

    Env vars:
      MAX_OPEN_POSITIONS   : limite (default 0 = disabled)
    """
    _max_open = int(os.getenv("MAX_OPEN_POSITIONS", "0"))
    if _max_open <= 0:
        return True, ""

    # --- Source 1: registre actif par mint (réconcilié avec DB) ---
    _active_count = _reconcile_exposure()

    if _active_count >= 0:
        # Hint DB pour comparaison (log seulement)
        _db_hint = _count_db_open()
        _source = f"active_file={_active_count}, db_hint={_db_hint}"

        if _active_count >= _max_open:
            msg = f"🛑 MAX_OPEN_POSITIONS: {_active_count}/{_max_open} active [{_source}] → skip BUY"
            print(msg, flush=True)
            return False, msg
        else:
            print(
                f"📊 MAX_OPEN_POSITIONS: {_active_count}/{_max_open} active [{_source}] (OK)", flush=True
            )
            return True, ""
    else:
        # Fichier indisponible → fallback DB OPEN count
        _db_count = _count_db_open()
        if _db_count >= 0:
            _source = f"db_fallback={_db_count}(file unavailable)"
            if _db_count >= _max_open:
                msg = f"🛑 MAX_OPEN_POSITIONS: {_db_count}/{_max_open} [{_source}] → skip BUY"
                print(msg, flush=True)
                return False, msg
            else:
                print(f"📊 MAX_OPEN_POSITIONS: {_db_count}/{_max_open} [{_source}] (OK)", flush=True)
                return True, ""
        else:
            print(f"⚠️ MAX_OPEN_POSITIONS: no reliable source (fail-open)", flush=True)
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
