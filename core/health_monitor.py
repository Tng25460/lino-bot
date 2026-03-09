"""
PHASE4_P4.8: Health Monitor — monitoring systeme non-bloquant.

Collecte l'etat de sante de tous les sous-systemes et ecrit
state/health.json pour monitoring externe (dashboard, alertes, etc.).

Caracteristiques:
- Lecture seule (aucune modification de DB ou d'etat)
- Non-bloquant (timeout sur chaque probe)
- Fail-open (chaque probe isolee — une erreur ne bloque pas les autres)
- Compatible run_live.py (appele periodiquement depuis le main loop)
- Aucune dependance dure (tout est importe dynamiquement)

Usage:
    from core.health_monitor import collect_health, write_health_json
    health = collect_health()
    write_health_json(health)
"""
from __future__ import annotations
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict

# ============================================================
# Configuration (env-configurable)
# ============================================================
HEALTH_OUTPUT_PATH = os.getenv("HEALTH_OUTPUT_PATH", "state/health.json")
HEARTBEAT_DIR = os.getenv("HEARTBEAT_DIR", "state")
READY_FILE = os.getenv("READY_FILE", "state/ready_to_trade.json")
BRAIN_DB_PATH = os.getenv("BRAIN_DB_PATH", os.getenv("BRAIN_DB", "state/brain.sqlite"))
TRADES_DB_PATH = os.getenv("TRADES_DB_PATH", os.getenv("DB_PATH", "state/trades.sqlite"))

# Seuils de staleness (secondes)
HEARTBEAT_STALE_SEC = int(os.getenv("HEALTH_HEARTBEAT_STALE_SEC", "120"))
READY_FILE_STALE_SEC = int(os.getenv("HEALTH_READY_STALE_SEC", "600"))
BRAIN_FILE_STALE_SEC = int(os.getenv("HEALTH_BRAIN_STALE_SEC", "300"))
MAX_OPEN_POSITIONS_WARN = int(os.getenv("HEALTH_MAX_OPEN_WARN", "20"))


# ============================================================
# Probes individuelles (chacune isolee en try/except)
# ============================================================

def _probe_heartbeats() -> Dict[str, Any]:
    """Verifie l'age des heartbeat files (buy + sell loops)."""
    result = {
        "buy_loop_alive": False,
        "sell_loop_alive": False,
        "buy_heartbeat_age_s": -1,
        "sell_heartbeat_age_s": -1,
    }
    now = time.time()
    hb_dir = Path(HEARTBEAT_DIR)

    for name in ("buy", "sell"):
        try:
            hb_file = hb_dir / f"heartbeat_{name}.txt"
            if hb_file.exists():
                ts = int(hb_file.read_text(encoding="utf-8").strip())
                age = int(now - ts)
                result[f"{name}_heartbeat_age_s"] = age
                result[f"{name}_loop_alive"] = age < HEARTBEAT_STALE_SEC
        except Exception:
            pass

    return result


def _probe_ready_file() -> Dict[str, Any]:
    """Verifie si le fichier ready_to_trade.json est frais."""
    result = {
        "ready_file_exists": False,
        "ready_file_stale": True,
        "ready_file_age_s": -1,
        "ready_candidates": 0,
    }
    try:
        rf = Path(READY_FILE)
        if rf.exists():
            result["ready_file_exists"] = True
            mtime = rf.stat().st_mtime
            age = int(time.time() - mtime)
            result["ready_file_age_s"] = age
            result["ready_file_stale"] = age > READY_FILE_STALE_SEC
            try:
                data = json.loads(rf.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    result["ready_candidates"] = len(data)
                elif isinstance(data, dict):
                    result["ready_candidates"] = len(data.get("tokens", data.get("candidates", [])))
            except Exception:
                pass
    except Exception:
        pass
    return result


def _probe_brain_db() -> Dict[str, Any]:
    """Verifie l'etat de brain.sqlite."""
    result = {
        "brain_alive": False,
        "brain_file_stale": True,
        "brain_file_age_s": -1,
        "decision_log_count": 0,
        "decision_log_last_age_s": -1,
        "regime_last": "UNKNOWN",
        "regime_confidence": 0.0,
    }
    try:
        bp = Path(BRAIN_DB_PATH)
        if not bp.exists():
            return result

        mtime = bp.stat().st_mtime
        age = int(time.time() - mtime)
        result["brain_file_age_s"] = age
        result["brain_file_stale"] = age > BRAIN_FILE_STALE_SEC

        con = sqlite3.connect(str(bp), timeout=3.0)
        con.execute("PRAGMA journal_mode=WAL")
        con.row_factory = sqlite3.Row

        # decision_log count + age derniere entree
        try:
            row = con.execute(
                "SELECT COUNT(*) as cnt, MAX(ts) as last_ts FROM decision_log"
            ).fetchone()
            if row:
                result["decision_log_count"] = int(row["cnt"] or 0)
                last_ts = int(row["last_ts"] or 0)
                if last_ts > 0:
                    result["decision_log_last_age_s"] = int(time.time() - last_ts)
        except Exception:
            pass

        # dernier regime
        try:
            row = con.execute(
                "SELECT regime, confidence FROM regime_snapshots "
                "ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            if row:
                result["regime_last"] = str(row["regime"] or "UNKNOWN")
                result["regime_confidence"] = float(row["confidence"] or 0.0)
        except Exception:
            pass

        result["brain_alive"] = True
        con.close()
    except Exception:
        pass
    return result


def _probe_risk_state() -> Dict[str, Any]:
    """Lit le risk_state depuis risk_engine."""
    try:
        from core.risk_engine import get_risk_summary
        return {"risk_state": get_risk_summary()}
    except Exception:
        return {"risk_state": {}}


def _probe_open_positions() -> Dict[str, Any]:
    """Compte les positions ouvertes dans trades.sqlite."""
    result = {
        "open_positions": 0,
        "open_positions_warn": False,
    }
    try:
        tp = Path(TRADES_DB_PATH)
        if not tp.exists():
            return result
        con = sqlite3.connect(str(tp), timeout=3.0)
        con.execute("PRAGMA journal_mode=WAL")
        row = con.execute(
            "SELECT COUNT(*) FROM positions WHERE status LIKE 'OPEN%'"
        ).fetchone()
        con.close()
        if row:
            n = int(row[0] or 0)
            result["open_positions"] = n
            result["open_positions_warn"] = n > MAX_OPEN_POSITIONS_WARN
    except Exception:
        pass
    return result


def _probe_decision_stats() -> Dict[str, Any]:
    """Calcule les stats recentes depuis decision_log (5 dernieres minutes)."""
    result = {
        "rate_429": 0.0,
        "swap_failure_rate": 0.0,
        "quote_failure_rate": 0.0,
        "recent_buys": 0,
        "recent_rejects": 0,
        "recent_skips": 0,
    }
    try:
        bp = Path(BRAIN_DB_PATH)
        if not bp.exists():
            return result

        con = sqlite3.connect(str(bp), timeout=3.0)
        con.execute("PRAGMA journal_mode=WAL")

        window = int(os.getenv("HEALTH_STATS_WINDOW_SEC", "300"))
        cutoff = int(time.time()) - window

        rows = con.execute(
            "SELECT action, reason FROM decision_log WHERE ts >= ?",
            (cutoff,)
        ).fetchall()
        con.close()

        if not rows:
            return result

        total = len(rows)
        n_429 = 0
        n_quote_fail = 0
        n_swap_fail = 0
        n_buy = 0
        n_reject = 0
        n_skip = 0

        for action, reason in rows:
            action = str(action or "").upper()
            reason = str(reason or "").lower()

            if action == "BUY":
                n_buy += 1
            elif action == "REJECT":
                n_reject += 1
            elif action == "SKIP":
                n_skip += 1

            if "429" in reason:
                n_429 += 1
            if "quote_http" in reason or "quote_exception" in reason:
                n_quote_fail += 1
            if "swap_http" in reason or "swap_exception" in reason or "swap_no_tx" in reason:
                n_swap_fail += 1

        result["recent_buys"] = n_buy
        result["recent_rejects"] = n_reject
        result["recent_skips"] = n_skip
        result["rate_429"] = round(n_429 / total, 3) if total > 0 else 0.0
        result["quote_failure_rate"] = round(n_quote_fail / total, 3) if total > 0 else 0.0
        result["swap_failure_rate"] = round(n_swap_fail / total, 3) if total > 0 else 0.0
    except Exception:
        pass
    return result


def _probe_rpc_health() -> Dict[str, Any]:
    """Teste la sante RPC avec un getHealth (timeout 5s)."""
    result = {
        "rpc_ok": False,
        "rpc_latency_ms": -1,
    }
    try:
        import requests
        rpc = os.getenv(
            "RPC_HTTP",
            os.getenv("SOLANA_RPC_HTTP",
            os.getenv("SOLANA_RPC_URL",
            os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")))
        )
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getHealth"}
        t0 = time.time()
        r = requests.post(rpc, json=payload, timeout=5.0)
        elapsed_ms = int((time.time() - t0) * 1000)
        result["rpc_latency_ms"] = elapsed_ms

        if r.status_code == 200:
            data = r.json()
            # getHealth returns {"result": "ok"} when healthy
            res = data.get("result", "")
            result["rpc_ok"] = (res == "ok")
        else:
            result["rpc_ok"] = False
    except Exception:
        pass
    return result


def _probe_jupiter_health() -> Dict[str, Any]:
    """Teste la latence Jupiter via un quote trivial (timeout 5s)."""
    result = {
        "jupiter_ok": False,
        "jupiter_latency_ms": -1,
    }
    try:
        import requests
        base = os.getenv("JUP_API_BASE", os.getenv("JUP_BASE_URL", "https://lite-api.jup.ag"))
        # SOL -> USDC, 1 lamport (trivial quote to test latency)
        url = f"{base}/swap/v1/quote"
        params = {
            "inputMint": "So11111111111111111111111111111111111111112",
            "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": "1",
            "slippageBps": "100",
        }
        t0 = time.time()
        r = requests.get(url, params=params, timeout=5.0)
        elapsed_ms = int((time.time() - t0) * 1000)
        result["jupiter_latency_ms"] = elapsed_ms

        if r.status_code == 200:
            result["jupiter_ok"] = True
        elif r.status_code == 429:
            result["jupiter_ok"] = False
            result["jupiter_rate_limited"] = True
    except Exception:
        pass
    return result


def _probe_db_integrity() -> Dict[str, Any]:
    """Verifie l'integrite SQLite (pas de lock, pas de corruption)."""
    result = {
        "trades_db_ok": False,
        "brain_db_ok": False,
    }
    for label, path in [("trades_db_ok", TRADES_DB_PATH), ("brain_db_ok", BRAIN_DB_PATH)]:
        try:
            p = Path(path)
            if not p.exists():
                continue
            con = sqlite3.connect(str(p), timeout=2.0)
            con.execute("PRAGMA integrity_check")
            # Si on arrive ici, pas de lock ni corruption
            result[label] = True
            con.close()
        except Exception:
            pass
    return result


def _probe_onchain_stats() -> Dict[str, Any]:
    """AXE2: stats du detecteur onchain (shadow mode)."""
    try:
        from core.onchain_detector import get_onchain_stats
        return get_onchain_stats()
    except Exception:
        return {
            "onchain_candidates_5m": 0,
            "onchain_avg_score": 0.0,
            "onchain_max_score": 0.0,
            "onchain_in_ready": 0,
        }


def _probe_kill_switch() -> Dict[str, Any]:
    """AXE2: etat du kill switch."""
    try:
        ks = Path(os.getenv("KILL_SWITCH_FILE", "state/KILL_SWITCH"))
        return {"kill_switch_active": ks.exists()}
    except Exception:
        return {"kill_switch_active": False}


def _probe_wallet_balance() -> Dict[str, Any]:
    """AXE2: solde SOL du wallet (via RPC getBalance, timeout 3s)."""
    result = {"wallet_sol": -1.0, "wallet_pubkey": ""}
    try:
        import requests
        rpc = os.getenv(
            "RPC_HTTP",
            os.getenv("SOLANA_RPC_HTTP",
            os.getenv("SOLANA_RPC_URL",
            os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")))
        )
        # Fallback chain: WALLET_PUBKEY > TRADER_USER_PUBLIC_KEY > extract from keypair
        pubkey = (
            os.getenv("WALLET_PUBKEY", "").strip()
            or os.getenv("TRADER_USER_PUBLIC_KEY", "").strip()
        )
        if not pubkey:
            # Dernier recours: extraire du keypair si disponible
            try:
                kp_path = os.getenv("SOLANA_KEYPAIR", "") or os.getenv("KEYPAIR_PATH", "")
                if kp_path:
                    import json as _j
                    _arr = _j.loads(Path(kp_path).expanduser().read_text(encoding="utf-8"))
                    if isinstance(_arr, list) and len(_arr) >= 64:
                        from solders.keypair import Keypair as _Kp  # type: ignore
                        _kp = _Kp.from_bytes(bytes(int(x) & 0xFF for x in _arr[:64]))
                        pubkey = str(_kp.pubkey())
            except Exception:
                pass
        if not pubkey:
            result["_wallet_error"] = "no WALLET_PUBKEY/TRADER_USER_PUBLIC_KEY/SOLANA_KEYPAIR"
            return result
        result["wallet_pubkey"] = pubkey[:8] + "…"
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getBalance",
            "params": [pubkey, {"commitment": "processed"}],
        }
        r = requests.post(rpc, json=payload, timeout=3.0)
        if r.status_code == 200:
            data = r.json()
            if "error" in data:
                result["_wallet_error"] = str(data["error"])[:100]
            else:
                lamports = int(data.get("result", {}).get("value", 0))
                result["wallet_sol"] = round(lamports / 1_000_000_000, 6)
        else:
            result["_wallet_error"] = f"http_{r.status_code}"
    except Exception as e:
        result["_wallet_error"] = str(e)[:100]
    return result


# ============================================================
# Collecteur principal
# ============================================================

def collect_health() -> Dict[str, Any]:
    """
    Execute toutes les probes et retourne un dict complet.
    Chaque probe est isolee: si l'une echoue, les autres continuent.
    """
    health: Dict[str, Any] = {
        "ts": int(time.time()),
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
    }

    probes = [
        _probe_heartbeats,
        _probe_ready_file,
        _probe_brain_db,
        _probe_risk_state,
        _probe_open_positions,
        _probe_decision_stats,
        _probe_rpc_health,
        _probe_jupiter_health,
        _probe_db_integrity,
        _probe_onchain_stats,       # AXE2: shadow detector stats
        _probe_kill_switch,         # AXE2: kill switch state
        _probe_wallet_balance,      # AXE2: SOL balance
    ]

    for probe in probes:
        try:
            result = probe()
            if isinstance(result, dict):
                health.update(result)
        except Exception as e:
            try:
                health[f"_error_{probe.__name__}"] = str(e)[:200]
            except Exception:
                pass

    # Synthese: overall health
    try:
        health["overall_ok"] = (
            health.get("rpc_ok", False)
            and health.get("brain_alive", False)
            and health.get("trades_db_ok", False)
            and health.get("buy_loop_alive", False)
            and health.get("sell_loop_alive", False)
            and not health.get("open_positions_warn", False)
            and not health.get("kill_switch_active", False)
        )
    except Exception:
        health["overall_ok"] = False

    # Regime pour acces rapide
    try:
        health["regime"] = health.get("regime_last", "UNKNOWN")
    except Exception:
        pass

    return health


# ============================================================
# Ecriture JSON (atomique via rename)
# ============================================================

def write_health_json(health: Dict[str, Any], path: str = "") -> bool:
    """
    Ecrit health dans state/health.json (atomique).
    Retourne True si succes, False sinon (fail-open).
    """
    try:
        out_path = path or HEALTH_OUTPUT_PATH
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Ecriture atomique via fichier temporaire + rename
        import tempfile
        fd, tmp = tempfile.mkstemp(
            prefix=".health_", suffix=".json", dir=str(out.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(health, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(tmp, str(out))
            return True
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except Exception:
                pass
            return False
    except Exception:
        return False


# ============================================================
# Point d'entree CLI (pour test standalone)
# ============================================================

def run_health_check(verbose: bool = True) -> Dict[str, Any]:
    """Execute une collecte + ecriture. Retourne le health dict."""
    health = collect_health()
    write_health_json(health)
    if verbose:
        print(json.dumps(health, indent=2, ensure_ascii=False), flush=True)
    return health


if __name__ == "__main__":
    run_health_check()
