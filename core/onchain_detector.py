"""
PHASE5_P5.0: On-chain Detector — detection precoce shadow mode.

Architecture fast lane:
  event on-chain → candidate → enrichissement rapide → scoring → log

Ce module ecoute les evenements on-chain (Helius WebSocket, polling RPC)
et produit des candidats pre-scores, loggues dans brain.sqlite pour
analyse et comparaison avec le pipeline classique (DexScreener ready).

MODE: SHADOW UNIQUEMENT — aucun BUY, aucun trade, juste observation.

Sources supportees (par priorite):
  1. Helius logsSubscribe (WebSocket) — plus rapide, ~1-2s apres le tx
  2. RPC getSignaturesForAddress polling — fallback si pas de WS
  3. Pump.fun program monitoring — creation de tokens
  4. Raydium pool creation — premiere liquidite

Pipeline:
  detect_event() → build_candidate() → fast_enrich() → fast_score() → log_candidate()

Stockage:
  - brain.sqlite → onchain_candidates (nouvelle table)
  - state/onchain_candidates.json (buffer recents pour debug)

Activation:
  ONCHAIN_DETECTOR_ENABLED=1  (defaut OFF)

Fail-open: chaque etape isolee en try/except. Si le detector crash,
le bot continue normalement avec le pipeline classique.
"""
from __future__ import annotations
import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ============================================================
# Configuration
# ============================================================
ENABLED = os.getenv("ONCHAIN_DETECTOR_ENABLED", "0").strip() in ("1", "true", "yes")
BRAIN_DB_PATH = os.getenv("BRAIN_DB_PATH", os.getenv("BRAIN_DB", "state/brain.sqlite"))
CANDIDATES_JSON = os.getenv("ONCHAIN_CANDIDATES_JSON", "state/onchain_candidates.json")
MAX_CANDIDATES_BUFFER = int(os.getenv("ONCHAIN_MAX_BUFFER", "200"))

# Programme IDs
PUMPFUN_PROGRAM = os.getenv("PUMPFUN_PROGRAM", "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
RAYDIUM_AMM_V4 = os.getenv("RAYDIUM_AMM_V4", "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
RAYDIUM_CLMM = os.getenv("RAYDIUM_CLMM", "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK")

# RPC
RPC_HTTP = os.getenv(
    "RPC_HTTP",
    os.getenv("SOLANA_RPC_HTTP",
    os.getenv("SOLANA_RPC_URL",
    os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")))
)
RPC_WS = os.getenv(
    "RPC_WS",
    os.getenv("SOLANA_RPC_WS", "")
)

# Polling config
POLL_INTERVAL_SEC = float(os.getenv("ONCHAIN_POLL_SEC", "3.0"))
RECENT_WINDOW_SEC = float(os.getenv("ONCHAIN_RECENT_WINDOW_SEC", "60"))

# Mints systeme a ignorer
IGNORE_MINTS = {
    "So11111111111111111111111111111111111111112",   # WSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",    # USDT
}


# ============================================================
# Schema SQLite (table onchain_candidates)
# ============================================================
_SCHEMA_ONCHAIN = """
CREATE TABLE IF NOT EXISTS onchain_candidates (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               INTEGER NOT NULL,
    mint             TEXT    NOT NULL,
    symbol           TEXT    DEFAULT '',
    source           TEXT    DEFAULT '',      -- pumpfun / raydium / helius
    event_type       TEXT    DEFAULT '',      -- create / migrate / first_liq / swap
    -- metriques rapides
    liq_sol          REAL    DEFAULT 0.0,
    market_cap_usd   REAL    DEFAULT 0.0,
    volume_5m_usd    REAL    DEFAULT 0.0,
    holder_count     INTEGER DEFAULT 0,
    dev_address      TEXT    DEFAULT '',
    -- scoring rapide
    fast_score       REAL    DEFAULT 0.0,     -- 0-100, pre-scoring rapide
    fast_explain     TEXT    DEFAULT '',       -- explication courte du score
    -- comparaison avec pipeline classique
    in_ready_file    INTEGER DEFAULT 0,       -- 1 si aussi present dans ready_to_trade.json
    ready_delay_sec  INTEGER DEFAULT 0,       -- delai entre detection onchain et apparition ready
    -- meta
    tx_signature     TEXT    DEFAULT '',
    block_time       INTEGER DEFAULT 0,
    details_json     TEXT    DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_onchain_ts ON onchain_candidates(ts);
CREATE INDEX IF NOT EXISTS idx_onchain_mint ON onchain_candidates(mint);
"""


def ensure_onchain_schema() -> None:
    """Cree la table onchain_candidates si elle n'existe pas."""
    try:
        os.makedirs(os.path.dirname(BRAIN_DB_PATH) or "state", exist_ok=True)
        con = sqlite3.connect(BRAIN_DB_PATH, timeout=5.0)
        con.executescript(_SCHEMA_ONCHAIN)
        con.close()
    except Exception as e:
        try:
            print(f"⚠️ onchain_detector.ensure_schema failed: {e}", flush=True)
        except Exception:
            pass


# ============================================================
# Candidate builder
# ============================================================

def build_candidate(
    mint: str,
    source: str,
    event_type: str,
    *,
    tx_sig: str = "",
    block_time: int = 0,
    dev_address: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construit un objet candidat standardise."""
    return {
        "ts": int(time.time()),
        "mint": str(mint),
        "symbol": "",
        "source": str(source),
        "event_type": str(event_type),
        "liq_sol": 0.0,
        "market_cap_usd": 0.0,
        "volume_5m_usd": 0.0,
        "holder_count": 0,
        "dev_address": str(dev_address),
        "fast_score": 0.0,
        "fast_explain": "",
        "in_ready_file": 0,
        "ready_delay_sec": 0,
        "tx_signature": str(tx_sig),
        "block_time": int(block_time),
        "details": details or {},
    }


# ============================================================
# Enrichissement rapide (non-bloquant, timeout court)
# ============================================================

def fast_enrich(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrichit un candidat avec des donnees rapides:
    - DexScreener prix/liq/MC (si dispo)
    - Verification ready_to_trade.json (comparaison pipeline)
    - Dev memory (brain.sqlite)

    Timeout: max 3s total. Chaque source isolee.
    """
    mint = candidate.get("mint", "")
    if not mint:
        return candidate

    # 1. DexScreener quick check
    try:
        import requests
        url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
        r = requests.get(url, timeout=3.0)
        if r.status_code == 200:
            data = r.json()
            pairs = data.get("pairs") or []
            if pairs:
                best = pairs[0]
                candidate["liq_sol"] = float(best.get("liquidity", {}).get("base", 0) or 0)
                candidate["market_cap_usd"] = float(best.get("marketCap", 0) or 0)
                vol = best.get("volume", {})
                candidate["volume_5m_usd"] = float(vol.get("m5", 0) or 0)
                candidate["symbol"] = str(best.get("baseToken", {}).get("symbol", "") or "")
    except Exception:
        pass

    # 2. Comparaison avec ready_to_trade.json
    try:
        rf = Path(os.getenv("READY_FILE", "state/ready_to_trade.json"))
        if rf.exists():
            data = json.loads(rf.read_text(encoding="utf-8"))
            if isinstance(data, list):
                ready_mints = {str(t.get("mint", t.get("address", ""))).strip() for t in data if isinstance(t, dict)}
            elif isinstance(data, dict):
                tokens = data.get("tokens", data.get("candidates", []))
                ready_mints = {str(t.get("mint", t.get("address", ""))).strip() for t in tokens if isinstance(t, dict)}
            else:
                ready_mints = set()

            if mint in ready_mints:
                candidate["in_ready_file"] = 1
                # Calculer le delai (si le ready file est plus ancien)
                rf_mtime = int(rf.stat().st_mtime)
                candidate["ready_delay_sec"] = max(0, int(time.time()) - rf_mtime)
    except Exception:
        pass

    # 3. Dev memory check
    try:
        dev = candidate.get("dev_address", "")
        if dev:
            con = sqlite3.connect(BRAIN_DB_PATH, timeout=2.0)
            row = con.execute(
                "SELECT blacklisted, n_rugged, avg_pnl FROM dev_memory WHERE dev_address=?",
                (dev,)
            ).fetchone()
            con.close()
            if row:
                if int(row[0] or 0) == 1:
                    candidate["details"]["dev_blacklisted"] = True
                candidate["details"]["dev_rugs"] = int(row[1] or 0)
                candidate["details"]["dev_avg_pnl"] = float(row[2] or 0)
    except Exception:
        pass

    return candidate


# ============================================================
# Fast scoring (pre-score rapide pour triage)
# ============================================================

def fast_score(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pre-score rapide (0-100) base sur les metriques disponibles.
    Pas aussi precis que scoring_elite, mais utilisable pour trier
    les candidats par potentiel et filtrer le bruit.

    Composantes:
      - Liquidite (0-20): sweet spot 5-50 SOL pour early
      - Market cap (0-20): sweet spot 10k-100k pour x100
      - Source (0-15): pumpfun migrate > raydium create > generic
      - Volume (0-15): volume 5min early activity
      - Dev rep (0-15): dev_memory bonus/malus
      - Timing (0-15): plus c'est tot, mieux c'est
    """
    score = 0.0
    explain_parts = []

    # 1. Liquidite
    try:
        liq = float(candidate.get("liq_sol", 0))
        if 5 <= liq <= 50:
            s = 20.0
        elif 50 < liq <= 200:
            s = 15.0
        elif 2 <= liq < 5:
            s = 12.0
        elif liq > 200:
            s = 8.0
        else:
            s = 3.0
        score += s
        explain_parts.append(f"liq={s:.0f}")
    except Exception:
        pass

    # 2. Market cap
    try:
        mc = float(candidate.get("market_cap_usd", 0))
        if 10_000 <= mc <= 100_000:
            s = 20.0  # sweet spot x100
        elif 100_000 < mc <= 500_000:
            s = 15.0
        elif 5_000 <= mc < 10_000:
            s = 12.0
        elif mc > 500_000:
            s = 5.0
        else:
            s = 2.0
        score += s
        explain_parts.append(f"mc={s:.0f}")
    except Exception:
        pass

    # 3. Source
    try:
        source = str(candidate.get("source", "")).lower()
        event = str(candidate.get("event_type", "")).lower()
        if "pump" in source and "migrat" in event:
            s = 15.0  # pump.fun migration = forte conviction
        elif "pump" in source:
            s = 12.0
        elif "raydium" in source:
            s = 10.0
        else:
            s = 5.0
        score += s
        explain_parts.append(f"src={s:.0f}")
    except Exception:
        pass

    # 4. Volume 5min
    try:
        vol = float(candidate.get("volume_5m_usd", 0))
        if vol > 50_000:
            s = 15.0
        elif vol > 10_000:
            s = 12.0
        elif vol > 1_000:
            s = 8.0
        elif vol > 0:
            s = 4.0
        else:
            s = 0.0
        score += s
        explain_parts.append(f"vol={s:.0f}")
    except Exception:
        pass

    # 5. Dev reputation
    try:
        details = candidate.get("details", {}) or {}
        if details.get("dev_blacklisted"):
            s = -10.0  # malus fort
        elif details.get("dev_rugs", 0) > 0:
            s = -5.0
        elif details.get("dev_avg_pnl", 0) > 0.1:
            s = 15.0  # dev historiquement profitable
        else:
            s = 7.5  # neutre
        score += s
        explain_parts.append(f"dev={s:.0f}")
    except Exception:
        pass

    # 6. Timing (fraicheur)
    try:
        age = int(time.time()) - int(candidate.get("block_time", 0) or candidate.get("ts", 0))
        if age < 10:
            s = 15.0  # ultra early
        elif age < 30:
            s = 12.0
        elif age < 60:
            s = 8.0
        elif age < 300:
            s = 4.0
        else:
            s = 1.0
        score += s
        explain_parts.append(f"age={s:.0f}")
    except Exception:
        pass

    # Clamp 0-100
    score = max(0.0, min(100.0, score))

    candidate["fast_score"] = round(score, 1)
    candidate["fast_explain"] = " ".join(explain_parts)
    return candidate


# ============================================================
# Log candidate (brain.sqlite + JSON buffer)
# ============================================================

def log_candidate(candidate: Dict[str, Any]) -> None:
    """
    Persiste un candidat dans brain.sqlite → onchain_candidates
    et dans le buffer JSON pour debug.
    """
    # 1. SQLite
    try:
        ensure_onchain_schema()
        con = sqlite3.connect(BRAIN_DB_PATH, timeout=3.0)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            """INSERT INTO onchain_candidates
            (ts, mint, symbol, source, event_type, liq_sol, market_cap_usd,
             volume_5m_usd, holder_count, dev_address, fast_score, fast_explain,
             in_ready_file, ready_delay_sec, tx_signature, block_time, details_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(candidate.get("ts", int(time.time()))),
                str(candidate.get("mint", "")),
                str(candidate.get("symbol", "")),
                str(candidate.get("source", "")),
                str(candidate.get("event_type", "")),
                float(candidate.get("liq_sol", 0)),
                float(candidate.get("market_cap_usd", 0)),
                float(candidate.get("volume_5m_usd", 0)),
                int(candidate.get("holder_count", 0)),
                str(candidate.get("dev_address", "")),
                float(candidate.get("fast_score", 0)),
                str(candidate.get("fast_explain", "")),
                int(candidate.get("in_ready_file", 0)),
                int(candidate.get("ready_delay_sec", 0)),
                str(candidate.get("tx_signature", "")),
                int(candidate.get("block_time", 0)),
                json.dumps(candidate.get("details", {}), ensure_ascii=False),
            )
        )
        con.commit()
        con.close()
    except Exception as e:
        try:
            print(f"⚠️ onchain_detector.log_candidate DB failed: {e}", flush=True)
        except Exception:
            pass

    # 2. JSON buffer (recent candidates pour debug)
    try:
        out = Path(CANDIDATES_JSON)
        out.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

        # Prepend (plus recent en premier)
        safe_candidate = {k: v for k, v in candidate.items() if k != "details"}
        safe_candidate["details"] = str(candidate.get("details", {}))[:500]
        existing.insert(0, safe_candidate)
        existing = existing[:MAX_CANDIDATES_BUFFER]

        out.write_text(
            json.dumps(existing, ensure_ascii=False, indent=1),
            encoding="utf-8"
        )
    except Exception:
        pass


# ============================================================
# Detecteurs par source
# ============================================================

def _detect_pumpfun_rpc(session=None) -> List[Dict[str, Any]]:
    """
    Polling RPC: getSignaturesForAddress sur le programme Pump.fun.
    Retourne une liste de candidats bruts.
    """
    candidates = []
    try:
        import requests
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getSignaturesForAddress",
            "params": [
                PUMPFUN_PROGRAM,
                {"limit": 20, "commitment": "confirmed"}
            ]
        }
        r = requests.post(RPC_HTTP, json=payload, timeout=10.0)
        if r.status_code != 200:
            return []

        sigs = r.json().get("result", []) or []
        now = int(time.time())

        for sig_info in sigs:
            try:
                block_time = int(sig_info.get("blockTime", 0) or 0)
                if block_time > 0 and (now - block_time) > RECENT_WINDOW_SEC:
                    continue  # trop vieux
                if sig_info.get("err"):
                    continue  # tx echouee

                sig = str(sig_info.get("signature", ""))
                if not sig:
                    continue

                # On ne peut pas extraire le mint directement depuis getSignaturesForAddress
                # Le parsing detaille necessite getTransaction (couteux)
                # Pour la V1, on log la signature et on enrichira plus tard
                c = build_candidate(
                    mint="",  # sera enrichi par parsing TX
                    source="pumpfun",
                    event_type="program_activity",
                    tx_sig=sig,
                    block_time=block_time,
                )
                candidates.append(c)
            except Exception:
                continue
    except Exception as e:
        try:
            print(f"⚠️ pumpfun RPC poll failed: {e}", flush=True)
        except Exception:
            pass
    return candidates


def _detect_raydium_rpc() -> List[Dict[str, Any]]:
    """
    Polling RPC: getSignaturesForAddress sur Raydium AMM V4.
    Detecte les creations de pools (premiere liquidite).
    """
    candidates = []
    try:
        import requests
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getSignaturesForAddress",
            "params": [
                RAYDIUM_AMM_V4,
                {"limit": 10, "commitment": "confirmed"}
            ]
        }
        r = requests.post(RPC_HTTP, json=payload, timeout=10.0)
        if r.status_code != 200:
            return []

        sigs = r.json().get("result", []) or []
        now = int(time.time())

        for sig_info in sigs:
            try:
                block_time = int(sig_info.get("blockTime", 0) or 0)
                if block_time > 0 and (now - block_time) > RECENT_WINDOW_SEC:
                    continue
                if sig_info.get("err"):
                    continue

                sig = str(sig_info.get("signature", ""))
                if not sig:
                    continue

                c = build_candidate(
                    mint="",
                    source="raydium",
                    event_type="pool_activity",
                    tx_sig=sig,
                    block_time=block_time,
                )
                candidates.append(c)
            except Exception:
                continue
    except Exception as e:
        try:
            print(f"⚠️ raydium RPC poll failed: {e}", flush=True)
        except Exception:
            pass
    return candidates


def _parse_tx_for_mints(tx_sig: str) -> Optional[Dict[str, Any]]:
    """
    Parse une transaction pour extraire les mints impliques.
    Utilise getTransaction avec jsonParsed.
    Retourne un dict {mint, dev_address, event_type} ou None.
    """
    try:
        import requests
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getTransaction",
            "params": [
                tx_sig,
                {"encoding": "jsonParsed", "commitment": "confirmed",
                 "maxSupportedTransactionVersion": 0}
            ]
        }
        r = requests.post(RPC_HTTP, json=payload, timeout=10.0)
        if r.status_code != 200:
            return None

        result = r.json().get("result")
        if not result:
            return None

        # Extraire les token balances post-tx pour trouver les mints
        meta = result.get("meta", {}) or {}
        post_balances = meta.get("postTokenBalances", []) or []

        # Trouver les mints non-systeme
        found_mints = set()
        dev_address = ""
        for bal in post_balances:
            mint = str(bal.get("mint", ""))
            if mint and mint not in IGNORE_MINTS:
                found_mints.add(mint)
                if not dev_address:
                    dev_address = str(bal.get("owner", ""))

        # Signer = probable createur
        if not dev_address:
            try:
                tx_data = result.get("transaction", {})
                msg = tx_data.get("message", {})
                signer = msg.get("accountKeys", [{}])[0]
                if isinstance(signer, dict):
                    dev_address = str(signer.get("pubkey", ""))
                elif isinstance(signer, str):
                    dev_address = signer
            except Exception:
                pass

        if found_mints:
            # Prendre le premier mint non-systeme
            mint = list(found_mints)[0]
            return {
                "mint": mint,
                "dev_address": dev_address,
                "event_type": "token_create",
                "all_mints": list(found_mints),
            }

    except Exception:
        pass
    return None


# ============================================================
# Pipeline principal
# ============================================================

def run_detection_cycle() -> int:
    """
    Execute un cycle de detection complet:
    1. Poll Pump.fun et Raydium
    2. Parse les TX pour extraire les mints
    3. Enrichir + scorer chaque candidat
    4. Logger dans brain.sqlite

    Retourne le nombre de candidats loggues.
    """
    if not ENABLED:
        return 0

    seen_sigs = set()
    raw_candidates = []

    # Collecter les signatures recentes
    try:
        pf = _detect_pumpfun_rpc()
        raw_candidates.extend(pf)
    except Exception:
        pass

    try:
        ry = _detect_raydium_rpc()
        raw_candidates.extend(ry)
    except Exception:
        pass

    logged = 0

    for raw in raw_candidates:
        try:
            sig = raw.get("tx_signature", "")
            if not sig or sig in seen_sigs:
                continue
            seen_sigs.add(sig)

            # Parser la TX pour extraire le mint
            parsed = _parse_tx_for_mints(sig)
            if not parsed or not parsed.get("mint"):
                continue

            mint = parsed["mint"]
            if mint in IGNORE_MINTS:
                continue

            # Construire le candidat complet
            candidate = build_candidate(
                mint=mint,
                source=raw.get("source", "unknown"),
                event_type=parsed.get("event_type", raw.get("event_type", "")),
                tx_sig=sig,
                block_time=raw.get("block_time", 0),
                dev_address=parsed.get("dev_address", ""),
                details={"all_mints": parsed.get("all_mints", [])},
            )

            # Enrichir
            candidate = fast_enrich(candidate)

            # Scorer
            candidate = fast_score(candidate)

            # Logger
            log_candidate(candidate)
            logged += 1

            try:
                print(
                    f"🔍 ONCHAIN mint={mint[:8]}… src={candidate['source']}"
                    f" score={candidate['fast_score']:.0f}"
                    f" mc=${candidate['market_cap_usd']:.0f}"
                    f" liq={candidate['liq_sol']:.1f}SOL"
                    f" ready={'✓' if candidate['in_ready_file'] else '✗'}"
                    f" [{candidate['fast_explain']}]",
                    flush=True,
                )
            except Exception:
                pass

        except Exception as e:
            try:
                print(f"⚠️ onchain candidate processing failed: {e}", flush=True)
            except Exception:
                pass

    return logged


# ============================================================
# Loop async (pour integration dans run_live.py)
# ============================================================

async def onchain_detector_loop():
    """
    Loop async pour detection continue.
    A integrer dans run_live.py avec asyncio.gather.
    S'arrete proprement si ONCHAIN_DETECTOR_ENABLED passe a 0.
    """
    if not ENABLED:
        print("🔇 onchain_detector: DISABLED (ONCHAIN_DETECTOR_ENABLED=0)", flush=True)
        return

    print(
        f"🔍 onchain_detector: SHADOW MODE started"
        f" (poll={POLL_INTERVAL_SEC}s window={RECENT_WINDOW_SEC}s)",
        flush=True,
    )

    # Init schema
    try:
        ensure_onchain_schema()
    except Exception:
        pass

    cycle = 0
    while True:
        cycle += 1
        try:
            # Re-check enabled (hot reload)
            if os.getenv("ONCHAIN_DETECTOR_ENABLED", "0").strip() not in ("1", "true", "yes"):
                if cycle % 60 == 0:  # log toutes les ~3min
                    print("🔇 onchain_detector: paused (ONCHAIN_DETECTOR_ENABLED=0)", flush=True)
                await asyncio.sleep(POLL_INTERVAL_SEC)
                continue

            n = run_detection_cycle()
            if n > 0 and cycle % 10 == 0:
                print(f"🔍 onchain_detector: cycle={cycle} candidates={n}", flush=True)

        except Exception as e:
            try:
                print(f"⚠️ onchain_detector cycle error: {e}", flush=True)
            except Exception:
                pass

        await asyncio.sleep(POLL_INTERVAL_SEC)


# ============================================================
# Stats rapides (pour health_monitor)
# ============================================================

def get_onchain_stats(window_sec: int = 300) -> Dict[str, Any]:
    """Retourne les stats des candidats onchain recents."""
    try:
        con = sqlite3.connect(BRAIN_DB_PATH, timeout=2.0)
        con.execute("PRAGMA journal_mode=WAL")
        cutoff = int(time.time()) - window_sec

        row = con.execute(
            "SELECT COUNT(*), AVG(fast_score), MAX(fast_score), "
            "SUM(CASE WHEN in_ready_file=1 THEN 1 ELSE 0 END) "
            "FROM onchain_candidates WHERE ts >= ?",
            (cutoff,)
        ).fetchone()
        con.close()

        if row:
            return {
                "onchain_candidates_5m": int(row[0] or 0),
                "onchain_avg_score": round(float(row[1] or 0), 1),
                "onchain_max_score": round(float(row[2] or 0), 1),
                "onchain_in_ready": int(row[3] or 0),
            }
    except Exception:
        pass
    return {
        "onchain_candidates_5m": 0,
        "onchain_avg_score": 0.0,
        "onchain_max_score": 0.0,
        "onchain_in_ready": 0,
    }


# ============================================================
# CLI standalone (test)
# ============================================================

if __name__ == "__main__":
    import sys

    # Force enable pour test CLI
    ENABLED = True
    print("🔍 onchain_detector: running single cycle (CLI test)...", flush=True)
    ensure_onchain_schema()
    n = run_detection_cycle()
    print(f"🔍 Done: {n} candidates logged", flush=True)

    # Afficher les stats
    stats = get_onchain_stats(window_sec=3600)
    print(f"📊 Stats (1h): {json.dumps(stats, indent=2)}", flush=True)
