from __future__ import annotations
import os as _os
import sqlite3

# PHASE4_P4.2: import trace non-bloquante pour decision_log
try:
    from core.decision_trace import trace as _dtrace_raw
except Exception:
    def _dtrace_raw(*a, **kw): pass  # fallback silencieux si module absent

# AXE1_FIX1: wrapper auto-inject regime=_current_regime si absent
# Evite d'oublier regime= dans chaque appel (13 sur 18 le manquaient)
# Note: _current_regime est un global (ligne ~30), accessible depuis ici
def _dtrace(*args, **kwargs):
    if 'regime' not in kwargs:
        try:
            kwargs['regime'] = _current_regime
        except Exception:
            pass
    return _dtrace_raw(*args, **kwargs)

# PHASE4_P4.2_FIX: garantir le flush des traces avant exit subprocess
# Sans cela, les daemon threads sont tues et les INSERT jamais commites
# atexit couvre TOUS les return 0 de main() sans modifier le flux
try:
    from core.decision_trace import flush_pending as _flush_traces
    import atexit as _atexit
    _atexit.register(_flush_traces, timeout=2.0)
except Exception:
    pass

# PHASE4_P4.4: import regime detector (fail-open)
_current_regime = "UNKNOWN"
try:
    from core.regime_detector import detect_regime as _detect_regime
except Exception:
    def _detect_regime(**kw): return {"regime": "UNKNOWN", "regime_score": 0.0, "confidence": 0.0}

# --- TRADER_RLSKIP_FILTER_V4 ---
# marker: TRADER_RLSKIP_FILTER_V4
def _rl_skip_is_active(mint: str) -> bool:
    try:
        import time as _t
        path = str(os.getenv("RL_SKIP_FILE", "state/rl_skip_mints.json")).strip() or "state/rl_skip_mints.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except FileNotFoundError:
            return False
        except Exception:
            return False
        now = int(_t.time())
        until = data.get(mint)
        if until is None:
            return False
        try:
            until = int(until)
        except Exception:
            return False
        return until > now
    except Exception:
        return False
# --- /TRADER_RLSKIP_FILTER_V4 ---

# --- REBUY_POOL_V1 ---
def _in_rebuy_pool(mint: str) -> bool:
    try:
        if int(os.getenv("ALLOW_REBUY_POOL","0")) != 1:
            return False
        fp = str(os.getenv("REBUY_POOL_FILE","state/rebuy_pool.txt")).strip()
        if not fp:
            return False
        try:
            with open(fp, "r", encoding="utf-8") as f:
                pool = {ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")}
        except FileNotFoundError:
            return False
        return mint in pool
    except Exception:
        return False
# --- /REBUY_POOL_V1 ---

import os

# --- HIST_BAD_RLSKIP_V2 ---
def _hist_bad_should_skip(output_mint: str):
    """Return (should_skip, msg, n_closed, avg_pnl, skip_sec)."""
    try:
        import os, sqlite3
        brain_path = str(os.getenv("BRAIN_DB_PATH", "state/brain.sqlite")).strip()
        min_n = int(os.getenv("HIST_SKIP_MIN_N", "3"))
        max_avg = float(os.getenv("HIST_SKIP_AVG_PNL_MAX", "0.0"))
        skip_sec = int(os.getenv("HIST_SKIP_SEC", "3600"))

        if not output_mint:
            return (False, "no_mint", 0, 0.0, skip_sec)

        con = sqlite3.connect(brain_path, timeout=3.0)
        row = con.execute("SELECT n_closed, avg_pnl FROM mint_hist WHERE mint=?", (output_mint.strip(),)).fetchone()
        con.close()

        if not row:
            return (False, "no_hist", 0, 0.0, skip_sec)

        n_closed = int(row[0] or 0)
        avg_pnl = float(row[1] or 0.0)

        if n_closed >= min_n and avg_pnl <= max_avg:
            msg = "🧠 HIST_BAD -> RL_SKIP mint=%s n=%d avg=%.4f (min_n=%d max_avg=%.4f sec=%d)" % (
                output_mint, n_closed, avg_pnl, min_n, max_avg, skip_sec
            )
            return (True, msg, n_closed, avg_pnl, skip_sec)

        return (False, "hist_ok n=%d avg=%.4f" % (n_closed, avg_pnl), n_closed, avg_pnl, skip_sec)
    except Exception as e:
        try:
            import os as _os
            skip_sec = int(os.getenv("HIST_SKIP_SEC", "3600"))
        except Exception:
            skip_sec = 3600
        return (False, "hist_skip_error: %s" % e, 0, 0.0, skip_sec)
# --- /HIST_BAD_RLSKIP_V2 ---



# --- FAKE_SWAP429_N_V1 ---
def _fake_swap429_should_exit():
    try:
        n = int(float(os.getenv("FAKE_SWAP429_N", "0")))
    except Exception:
        n = 0
    if n <= 0:
        return False
    path = os.getenv("FAKE_SWAP429_ONCE_PATH", "/tmp/lino_fake_swap429_n.flag")
    try:
        import json, time
        if os.path.exists(path):
            d = json.loads(open(path, "r", encoding="utf-8").read() or "{}")
        else:
            d = {"n": n}
        left = int(d.get("n", n))
        if left > 0:
            d["n"] = left - 1
            d["ts"] = time.time()
            open(path, "w", encoding="utf-8").write(json.dumps(d))
            return True
    except Exception:
        return True
    return False
# --- /FAKE_SWAP429_N_V1 ---


# PHASE3_P3.6: supprimé _exit_rc42_on_429_v1 (code mort, jamais appelée)

TRADER_QUOTE_ONLY = int(os.getenv("TRADER_QUOTE_ONLY", "0"))
# --- RL_SKIP (top-level) ---
_rl_skip = {}
# LOAD_RL_SKIP_FILE (step2)
try:
    import os as _os
    _rl_path = _os.getenv("RL_SKIP_FILE","state/rl_skip_mints.json")
    if _os.path.exists(_rl_path):
        with open(_rl_path, "r", encoding="utf-8", errors="ignore") as _f:
            _raw = (_f.read() or "").strip()
        if _raw:
            _rl_skip.update(__import__("json").loads(_raw))
except Exception as _e:
    print("rl_skip load failed:", _e, flush=True)
# /LOAD_RL_SKIP_FILE
# --- /RL_SKIP ---


# PHASE3_P3.6: supprimé _rl_skip_filter_ready (code mort, jamais appelée — le filtrage RL_SKIP
# est fait en inline dans main() via TRADER_RLSKIP_APPLY_V4)
# PHASE2_P2.6: supprimé 1ère _rl_skip_load (L.185, écrasée par L.304)
# PHASE2_P2.6: supprimé 1ère _rl_skip_save (L.195, écrasée par L.313)

def _rl_skip_add(mint: str, sec: int | None = None, reason: str = ''):
    """Add mint to RL skip map until now+sec.
    Backward compatible with old signature _rl_skip_add(mint).
    """
    import os, json, time as _time
    from pathlib import Path

    # RL_SKIP_FILE can be Path or str; normalize
    rl_file = None
    try:
        rl_file = RL_SKIP_FILE  # may exist elsewhere
    except Exception:
        rl_file = os.getenv('RL_SKIP_FILE', 'state/rl_skip_mints.json')
    if isinstance(rl_file, str):
        rl_file = Path(rl_file)

    if sec is None:
        sec = int(os.getenv('RL_SKIP_SEC', '180'))
    else:
        try:
            sec = int(sec)
        except Exception:
            sec = int(os.getenv('RL_SKIP_SEC', '180'))

    now = int(_time.time())
    until = now + int(sec)

    data = {}
    try:
        if rl_file.exists():
            data = json.loads(rl_file.read_text(errors='ignore') or '{}')
    except Exception:
        data = {}

    data[str(mint)] = int(until)
    try:
        rl_file.parent.mkdir(parents=True, exist_ok=True)
        rl_file.write_text(json.dumps(data, separators=(',',':')))
    except Exception as e:
        print(f"⚠️ RL_SKIP write failed file={rl_file} err={e}")
        return

    if reason:
        print(f"🧊 RL_SKIP add mint={mint} sec={sec} until={until} reason={reason}")
    else:
        print(f"🧊 RL_SKIP add mint={mint} sec={sec} until={until}")

# PHASE2_P2.6: supprimé 1ère _rl_skip_is (buggée: utilisait _rl_skip undefined, écrasée par L.282)
# PHASE2_P2.6: supprimé 2ème _rl_skip_load (écrasée par 3ème à L.290)

# === RL_SKIP_HELPERS ===
import json as _json
from pathlib import Path as _Path
RL_SKIP_FILE = os.getenv('RL_SKIP_FILE', 'state/rl_skip_mints.json')
RL_SKIP_SEC = int(os.getenv('RL_SKIP_SEC', '180'))

QUOTE_429_SLEEP_S = float(os.getenv('QUOTE_429_SLEEP_S', '1.5'))

def _rl_skip_is(mint: str) -> bool:
    m = (mint or '').strip()
    if not m:
        return False
    d = _rl_skip_load()
    until = float(d.get(m, 0) or 0)
    return until > time.time()

def _rl_skip_load() -> dict:
    try:
        fp = _Path(RL_SKIP_FILE)
        if not fp.exists():
            return {}
        return _json.loads(fp.read_text(encoding="utf-8", errors="ignore") or "{}")
    except Exception:
        return {}

def _rl_skip_save(d: dict) -> None:
    try:
        fp = _Path(RL_SKIP_FILE)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(_json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception as _e:
        print("⚠️ rl_skip save failed:", _e)

# PHASE3_P3.6: supprimé _rl_skip_has (code mort, jamais appelée — _rl_skip_is utilisée à la place)
# --- END RL skip ---


# PHASE1_P1.2: _jup_quote_with_retry SUPPRIMÉE (code mort + bug récursif infini).
# Le vrai appel Jupiter quote se fait directement via requests.get() dans main().
# Un helper retry partagé (buy+sell) sera ajouté en Phase 3 (modularisation).

# skip_mints split (trader vs brain)
TRADER_SKIP_MINTS_FILE = os.getenv('TRADER_SKIP_MINTS_FILE') or os.getenv('SKIP_MINTS_FILE') or 'state/skip_mints_trader.txt'
TRADER_AUTOSKIP_FILE = os.getenv("TRADER_AUTOSKIP_FILE", "state/skip_mints_trader.txt")
if str(TRADER_AUTOSKIP_FILE).endswith("skip_mints_trader.merged.txt"):
    print("⚠️ AUTOSKIP target merged interdit -> fallback state/skip_mints_trader.txt")
    TRADER_AUTOSKIP_FILE = "state/skip_mints_trader.txt"

# === POSTBUY_RESYNC_DB ===
# PHASE1_P1.3: supprimé _db_cols (doublon, écrasé par la def ligne ~412)
# PHASE1_P1.3: supprimé _pick_col (code mort, jamais appelée)

# PHASE3_P3.2: _onchain_ui_balance_stable extrait vers core/qty_resync.py
from core.qty_resync import _onchain_ui_balance_stable, resync_buy_inline


# PHASE1_P1.3: supprimé _postbuy_resync_db (fonction vide, jamais appelée).
# Le resync post-buy est fait par scripts/resync_buy_qty.py (appelé par trader_loop.py).

# PHASE3_P3.1: _db_cols, _db_insert, _db_record_buy_schema_safe extraits vers core/db_write.py
# Import centralisé — comportement 100% identique, zéro changement de logique.
from core.db_write import _db_record_buy_schema_safe

def _skip_file_path() -> str:
    try:
        import os
        return str(os.getenv('SKIP_MINTS_FILE','')).strip() or str(globals().get('SKIP_MINTS_FILE','state/skip_mints_trader.txt'))
    except Exception:
        return str(globals().get('SKIP_MINTS_FILE','state/skip_mints_trader.txt'))

def _append_skip_mint(mint: str):
    """Append mint to SKIP_MINTS_FILE (env-aware, best-effort, de-dup)."""
    try:
        import os
        m = (mint or '').strip()
        if not m:
            return
        sf = _skip_file_path().strip() or 'state/skip_mints_trader.txt'
        # de-dup: si le fichier est raisonnable, on évite de réécrire un mint déjà présent
        try:
            if os.path.exists(sf):
                sz = os.path.getsize(sf)
                if sz <= 1024*1024:  # 1MB
                    with open(sf, 'r', encoding='utf-8', errors='ignore') as f:
                        for ln in f:
                            if ln.strip() == m:
                                return
        except Exception:
            pass
        with open(sf, 'a', encoding='utf-8') as f:
            f.write(m + '\n')
    except Exception:
        return

def _autoskip_mint(mint: str):
    from pathlib import Path
    m = (mint or '').strip()
    if not m:
        return
    fp = Path(SKIP_MINTS_FILE)
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        with fp.open('a', encoding='utf-8') as f:
            f.write(m + '\n')
    except Exception as e:
        print(f"⚠️ autoskip write failed: {e}")
USE_SCORED_IF_PRESENT = os.getenv("USE_SCORED_IF_PRESENT", "1") == "1"
SCORED_TOPK = int(os.getenv("SCORED_TOPK", os.getenv("TOPK", "12")))
SKIP_MINTS_FILE = os.getenv("TRADER_SKIP_MINTS_FILE", "state/skip_mints_trader.txt")
SKIP_IF_BAG = os.getenv("SKIP_IF_BAG", "1") == "1"
BAG_MIN_UI = float(os.getenv("BAG_MIN_UI", "0.0"))
HOLDING_CACHE_FILE = os.getenv("HOLDING_CACHE_FILE", "state/holding_cache.json")
HOLDING_CACHE_TTL_S = int(float(os.getenv("HOLDING_CACHE_TTL_S", "7200")))  # 2h

def _holding_cache_load() -> dict:
    try:
        from pathlib import Path as _P
        f = _P(HOLDING_CACHE_FILE)
        if not f.exists():
            return {}
        return json.loads(f.read_text(errors="ignore") or "{}") if 'json' in globals() else {}
    except Exception:
        try:
            import json as _json
            from pathlib import Path as _P
            f = _P(HOLDING_CACHE_FILE)
            if not f.exists():
                return {}
            return _json.loads(f.read_text(errors="ignore") or "{}")
        except Exception:
            return {}

def _holding_cache_save(d: dict) -> None:
    try:
        import json as _json
        from pathlib import Path as _P
        _P(HOLDING_CACHE_FILE).write_text(_json.dumps(d, ensure_ascii=False))
    except Exception:
        pass

def _holding_cache_update(mint: str, ui: float) -> None:
    try:
        import time as _time
        d = _holding_cache_load()
        d[mint] = {"ui": float(ui), "ts": int(_time.time())}
        _holding_cache_save(d)
    except Exception:
        pass

def _holding_cache_get_recent_ui(mint: str) -> float:
    try:
        import time as _time
        d = _holding_cache_load()
        v = d.get(mint) or {}
        ui = float(v.get("ui") or 0.0)
        ts = int(v.get("ts") or 0)
        if ui > 0.0 and ts > 0 and (int(_time.time()) - ts) <= HOLDING_CACHE_TTL_S:
            return ui
        return 0.0
    except Exception:
        return 0.0



def _pick_best_scored_ready(rows: list[dict]) -> dict | None:
    if not rows:
        return None
        # RL_SKIP filter
        try:
            _before = len(rows)
            rows = [r for r in rows if not _rl_skip_is(str(r.get('mint') or r.get('output_mint') or ''))]
            _after = len(rows)
            if _after != _before:
                print(f"🧊 RL_SKIP filtered {_before-_after} rows", flush=True)
        except Exception as _e:
            print('⚠️ RL_SKIP filter failed:', _e, flush=True)
    rows2 = sorted(rows, key=lambda r: float(r.get("score") or -1e9), reverse=True)
    k = max(1, int(SCORED_TOPK))
    top = rows2[:k]

    import random
    scores = [float(r.get("score") or 0.0) for r in top]
    mn = min(scores) if scores else 0.0
    weights = [(s - mn + 1e-6) for s in scores]
    try:
        return random.choices(top, weights=weights, k=1)[0]
    except Exception:
        return top[0]


import json
import time
import base64
from pathlib import Path
from typing import Any, Dict, Optional

import requests


def _load_skip_mints() -> set[str]:
    try:
        from pathlib import Path
        fp = Path(SKIP_MINTS_FILE)
        if not fp.exists():
            return set()
        s=set()
        for line in fp.read_text(encoding="utf-8", errors="ignore").splitlines():
            line=line.strip()
            if not line or line.startswith("#"):
                continue
            s.add(line)
        return s
    except Exception:
        return set()

# ANTI_REBUY_LAST_BUY_V1
LAST_BUY_FILE = os.getenv('LAST_BUY_FILE', 'state/last_buy.json')
LAST_BUY_COOLDOWN_S = int(os.getenv('LAST_BUY_COOLDOWN_S', '900'))  # 15min default

def _last_buy_get():
    try:
        from pathlib import Path
        import json, time
        fp = Path(LAST_BUY_FILE)
        if not fp.exists():
            return None
        j = json.loads(fp.read_text(encoding='utf-8'))
        mint = str(j.get('mint') or '').strip()
        ts = int(j.get('ts') or 0)
        if not mint or ts <= 0:
            return None
        return {'mint': mint, 'ts': ts}
    except Exception:
        return None

def _last_buy_set(mint: str):
    try:
        from pathlib import Path
        import json, time
        m = (mint or '').strip()
        if not m:
            return
        fp = Path(LAST_BUY_FILE)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps({'mint': m, 'ts': int(time.time())}, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass

def _is_last_buy_blocked(mint: str) -> bool:
    try:
        import time
        m = (mint or '').strip()
        if not m:
            return False
        j = _last_buy_get()
        if not j:
            return False
        if j['mint'] != m:
            return False
        age = int(time.time()) - int(j['ts'])
        return age < LAST_BUY_COOLDOWN_S
    except Exception:
        return False

def _get_token_ui_balance(owner_pubkey: str, mint: str) -> float:
    # jsonParsed token accounts by owner+mint
    try:
        import requests
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [owner_pubkey, {"mint": mint}, {"encoding": "jsonParsed"}],
        }
        r = requests.post(RPC_HTTP, json=payload, timeout=20).json()
        accs = ((r.get("result") or {}).get("value") or [])
        ui = 0.0
        for a in accs:
            try:
                ui = float(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"] or 0.0)
            except Exception:
                pass
        return float(ui or 0.0)
    except Exception:
        return 0.0

BUY_COOLDOWN_S = int(os.getenv("BUY_COOLDOWN_S", "3600"))  # per-mint rebuy cooldown (seconds)
BYPASS_COOLDOWN = os.getenv("BYPASS_COOLDOWN","0") == "1"
LAST_BUYS_FILE = os.getenv("LAST_BUYS_FILE", "state/last_buys.json")


# PHASE3_P3.6: supprimé _load_last_buys + _save_last_buys (code mort, jamais appelées —
# _last_buy_set/_last_buy_get utilisent LAST_BUY_FILE singulier, pas LAST_BUYS_FILE)

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.message import to_bytes_versioned


### PICK_SCORE_V1 ###

def _f(x, d=0.0):
    try:
        if x is None:
            return float(d)
        if isinstance(x, (int, float)):
            return float(x)
        xs = str(x).strip().replace("%","")
        if xs == "":
            return float(d)
        return float(xs)
    except Exception:
        return float(d)

def _score_candidate(c: dict) -> (float, dict):
    """
    Score simple, robuste (utilise ce qui existe dans ready_to_trade.jsonl).
    Plus le score est haut, meilleur c'est.
    """
    liq = _f(c.get("liquidity_usd") or c.get("liq_usd") or (c.get("liquidity") or {}).get("usd"), 0.0)
    v5  = _f(c.get("vol5m_usd") or c.get("volume5m_usd") or c.get("vol_5m_usd") or c.get("volume_usd_5m"), 0.0)
    v1h = _f(c.get("vol1h_usd") or c.get("volume1h_usd") or c.get("vol_1h_usd") or c.get("volume_usd_1h"), 0.0)
    ch5 = _f(c.get("chg5m_pct") or c.get("change5m_pct") or c.get("priceChange5m") or (c.get("priceChange") or {}).get("m5"), 0.0)
    ch1 = _f(c.get("chg1h_pct") or c.get("change1h_pct") or c.get("priceChange1h") or (c.get("priceChange") or {}).get("h1"), 0.0)
    mc  = _f(c.get("marketcap_usd") or c.get("mc_usd") or c.get("fdv_usd") or c.get("fdv"), 0.0)

    # gates (env) — si pas set => défauts raisonnables
    MIN_LIQ_USD   = _f(os.getenv("MIN_LIQ_USD", "15000"), 15000)
    MIN_VOL5M_USD = _f(os.getenv("MIN_VOL5M_USD", "3000"), 3000)
    MIN_CHG5M_PCT = _f(os.getenv("MIN_CHG5M_PCT", "5"), 5)
    MAX_CHG5M_PCT = _f(os.getenv("MAX_CHG5M_PCT", "70"), 70)
    MIN_CHG1H_PCT = _f(os.getenv("MIN_CHG1H_PCT", "0"), 0)
    MAX_MC_USD    = _f(os.getenv("MAX_MC_USD", "0"), 0)   # 0 => no cap

    # hard rejects
    if liq < MIN_LIQ_USD:
        return -1.0, {"why": "liq", "liq": liq}
    if v5 < MIN_VOL5M_USD:
        return -1.0, {"why": "vol5m", "vol5m": v5}
    if ch5 < MIN_CHG5M_PCT or ch5 > MAX_CHG5M_PCT:
        return -1.0, {"why": "chg5m", "chg5m": ch5}
    if ch1 < MIN_CHG1H_PCT:
        return -1.0, {"why": "chg1h", "chg1h": ch1}
    if MAX_MC_USD > 0 and mc > MAX_MC_USD:
        return -1.0, {"why": "mc", "mc": mc}

    # score (pondérations simples)
    # - favorise volume court terme + liquidité + momentum (5m/1h)
    # - pénalise un peu mc trop gros
    score = 0.0
    score += min(v5 / 2000.0, 10.0)        # 0..10
    score += min(v1h / 20000.0, 6.0)       # 0..6
    score += min(liq / 25000.0, 6.0)       # 0..6
    score += min(ch5 / 10.0, 8.0)          # 0..8
    score += min(max(ch1, 0.0) / 20.0, 6.0)# 0..6
    if mc > 0:
        score -= min(mc / 5_000_000.0, 3.0) # 0..-3

    dbg = {"liq": liq, "v5": v5, "v1h": v1h, "ch5": ch5, "ch1": ch1, "mc": mc, "score": score}
    return float(score), dbg

# PHASE3_P3.6: supprimé _pick_best_ready (code mort, jamais appelée —
# _pick_best_scored_ready est utilisée à la place)
### SOL_BALANCE_GUARD_V1 ###
MIN_SOL_BUFFER_LAMPORTS = int(float(os.getenv('MIN_SOL_BUFFER_SOL','0.003')) * 1_000_000_000)  # fees/ATA buffer

def _get_balance_lamports(rpc_http: str, pubkey: str) -> int:
    try:
        rr = requests.post(rpc_http, json={'jsonrpc':'2.0','id':1,'method':'getBalance','params':[pubkey]}, timeout=20)
        return int((rr.json().get('result') or {}).get('value') or 0)
    except Exception:
        return 0



READY_FILE = Path(os.getenv("READY_FILE", "ready_to_trade.jsonl"))
# P3: Prefer READY_CANONICAL (merged onchain+ready) if available
try:
    _canonical = Path(os.getenv("READY_CANONICAL_FILE", "state/READY_CANONICAL.jsonl"))
    if _canonical.exists() and _canonical.stat().st_size > 10:
        # Only use if fresh (< 5 min old)
        _canonical_age = int(time.time()) - int(_canonical.stat().st_mtime)
        if _canonical_age < 300:
            READY_FILE = _canonical
            print(f"   ready_file= (from READY_CANONICAL) age={_canonical_age}s", flush=True)
except Exception:
    pass
# Prefer brain-scored file if available (overrides canonical if explicitly set)
try:
    _rsf = (os.getenv("READY_SCORED_FILE") or "").strip()
    if _rsf:
        _p = Path(_rsf)
        if _p.exists() and _p.stat().st_size > 0:
            READY_FILE = _p
            print("   ready_file= (from READY_SCORED_FILE)", READY_FILE, flush=True)
except Exception:
    pass
OUT_TX_B64 = Path(os.getenv("OUT_TX_B64", "last_swap_tx.b64"))
OUT_META = Path(os.getenv("OUT_META", "last_swap_meta.json"))
OUT_ERR = Path(os.getenv("OUT_ERR", "last_swap_error.json"))
OUT_DBG = Path(os.getenv("OUT_DBG", "last_swap_debug.log"))
OUT_SENT = Path(os.getenv("OUT_SENT", "last_swap_sent.json"))

JUP_BASE = (os.getenv("JUP_BASE_URL") or os.getenv("JUP_BASE") or os.getenv("JUPITER_BASE_URL") or "https://lite-api.jup.ag").rstrip("/")
RPC_HTTP = os.getenv("RPC_HTTP", os.getenv("SOLANA_RPC_HTTP", "https://api.mainnet-beta.solana.com"))

SOL_MINT = os.getenv("SOL_MINT", "So11111111111111111111111111111111111111112")

SLIPPAGE_BPS = int(float(os.getenv("SLIPPAGE_BPS", os.getenv("TRADER_SLIPPAGE_BPS", "120"))))
MAX_PRICE_IMPACT_PCT = float(os.getenv("MAX_PRICE_IMPACT_PCT", os.getenv("TRADER_MAX_PRICE_IMPACT_PCT", "1.5")))
DEFAULT_SOL_AMOUNT = float(os.getenv("TRADER_SOL_AMOUNT", os.getenv("BUY_AMOUNT_SOL", "0.01")))

ONE_SHOT = os.getenv("ONE_SHOT", os.getenv("TRADER_ONE_SHOT","0")).strip().lower() in ("1", "true", "yes", "on")
DRY_RUN = os.getenv("TRADER_DRY_RUN", os.getenv("DRY_RUN", "1")).strip().lower() in ("1", "true", "yes", "on")
SKIP_PREFLIGHT = os.getenv("TRADER_SKIP_PREFLIGHT", "0").strip().lower() in ("1", "true", "yes", "on")

WALLET_PUBKEY = (os.getenv("WALLET_PUBKEY") or os.getenv("TRADER_USER_PUBLIC_KEY") or "").strip()


def _append_dbg(line: str) -> None:
    try:
        OUT_DBG.parent.mkdir(parents=True, exist_ok=True)
        with OUT_DBG.open("a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except Exception:
        pass


def _write_err(kind: str, payload: Dict[str, Any]) -> None:
    try:
        OUT_ERR.write_text(json.dumps({"ts": int(_time.time()), "kind": kind, **payload}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _headers() -> Dict[str, str]:
    h = {"accept": "application/json"}
    k = os.getenv("JUPITER_API_KEY") or os.getenv("JUP_API_KEY") or ""
    if k:
        h["x-api-key"] = k
    return h


def _load_ready() -> list[dict]:
    if not READY_FILE.exists():
        return []
    out = []
    with READY_FILE.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _lamports_from_any(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str) and v.strip():
        try:
            if "." in v:
                return int(float(v))
            return int(v)
        except Exception:
            return None
    return None


def _load_keypair() -> Keypair:
    path = os.getenv("SOLANA_KEYPAIR") or os.getenv("KEYPAIR_PATH") or ""
    if not path:
        raise RuntimeError("Missing SOLANA_KEYPAIR env (path to keypair.json)")
    p = Path(path).expanduser()
    arr = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(arr, list) or len(arr) < 64:
        raise RuntimeError("Bad keypair.json format (expected list of 64 ints)")
    secret = bytes(int(x) & 0xFF for x in arr[:64])
    return Keypair.from_bytes(secret)


def _send_signed_b64(tx_b64: str, rpc_http: str) -> str:
    kp = _load_keypair()

    raw_tx = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    sig = kp.sign_message(to_bytes_versioned(raw_tx.message))
    signed_tx = VersionedTransaction.populate(raw_tx.message, [sig])

    encoded_tx = base64.b64encode(bytes(signed_tx)).decode("utf-8")

    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sendTransaction",
        "params": [
            encoded_tx,
            {
                "encoding": "base64",
                "skipPreflight": bool(SKIP_PREFLIGHT),
                "preflightCommitment": os.getenv("PREFLIGHT_COMMITMENT", "processed"),
                "maxRetries": int(os.getenv("SEND_MAX_RETRIES", "3")),
            },
        ],
    }
    r = requests.post(rpc_http, json=req, timeout=35)
    _append_dbg("SEND_STATUS=" + str(r.status_code))
    _append_dbg("SEND_BODY=" + (r.text[:2000] if r.text else ""))

    if r.status_code != 200:
        raise RuntimeError(f"sendTransaction http={r.status_code} body={r.text[:2000]}")

    j = r.json()
    if "error" in j:
        raise RuntimeError(f"sendTransaction error={j['error']}")
    res = j.get("result")
    if not res:
        raise RuntimeError(f"sendTransaction no result: {j}")
    return str(res)

def _row_mint(row: dict) -> str:
    """Extract mint/address from a READY row (READY_CANONICAL + other formats).
    Priority: mint (READY_CANONICAL) > outputMint (Jupiter-ish) > address (generic).
    """
    try:
        if not isinstance(row, dict):
            return ''
        return str(row.get('mint') or row.get('outputMint') or row.get('address') or '').strip()
    except Exception:
        return ''

def _drop_ready_mint(ready, mint: str):
    """Return a new ready list with entries matching mint removed."""
    try:
        if not mint:
            return ready
        if not isinstance(ready, list):
            return ready
        mm = str(mint).strip()
        if not mm:
            return ready
        out = []
        for r in ready:
            try:
                if _row_mint(r) == mm:
                    continue
            except Exception:
                pass
            out.append(r)
        return out
    except Exception:
        return ready

def _load_skip_set(path: str) -> set:
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return set()
    out = set()
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.add(line)
    return out

# PHASE3_P3.6: supprimé _load_rlskip_set (code mort, jamais appelée —
# _rl_skip_purge_and_save est utilisée à la place pour charger+purger en un pas)

def _rl_skip_purge_and_save(path: str, now: int, cap: int = 5000) -> dict:
    """Load rl_skip JSON, remove expired entries, clamp to cap most-recent, save if changed.
    Format: {mint: <unix_ts>}. Returns the post-purge dict.
    """
    import json as _j
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
        obj = _j.loads(raw or "{}")
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    n_before = len(obj)
    # purge expired entries
    obj = {m: v for m, v in obj.items()
           if isinstance(v, (int, float)) and int(v) > now}
    # clamp to cap most-recent entries
    if len(obj) > cap:
        obj = dict(sorted(obj.items(), key=lambda kv: kv[1], reverse=True)[:cap])
    n_after = len(obj)
    if n_after != n_before:
        print(f"[RL_SKIP] purge: before={n_before} after={n_after}", flush=True)
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(_j.dumps(obj, separators=(',', ':')), encoding="utf-8")
        except Exception:
            pass
    return obj


def main() -> int:
    if not WALLET_PUBKEY:
        print("❌ missing WALLET_PUBKEY/TRADER_USER_PUBLIC_KEY")
        raise SystemExit(1)  # fatal: wallet pubkey missing

    print("🚀 trader_exec BUY")

    # --- FAKE_SWAP429_N_V1 (test helper) ---
    try:
        if '_fake_swap429_should_exit' in globals() and _fake_swap429_should_exit():
            print("🧪 FAKE_SWAP429_N -> exit(42)", flush=True)
            raise SystemExit(42)
    except SystemExit:
        raise
    except Exception:
        pass
    # --- /FAKE_SWAP429_N_V1 ---
    # --- FAKE_SWAP429_ONCE_V2 (sentinel file, real once across subprocesses) ---
    try:
        _fake = str(os.getenv("FAKE_SWAP429_ONCE","0")).strip().lower() in ("1","true","yes","on")
        if _fake:
            _flag = os.getenv("FAKE_SWAP429_ONCE_PATH", "/tmp/lino_fake_swap429_once.flag")
            if not os.path.exists(_flag):
                try:
                    with open(_flag, "w", encoding="utf-8") as f:
                        f.write("1\n")
                except Exception:
                    pass
                print("❌ swap build failed http= 429", flush=True)
                print("🧊 BUY_429_DETECTED swap_build -> exit(42)", flush=True)
                raise SystemExit(42)
    except SystemExit:
        raise
    except Exception:
        pass
    # --- /FAKE_SWAP429_ONCE_V2 ---


    # --- FORCE_RC42_V1 ---
    try:
        if str(os.getenv("FORCE_RC42","0")).strip().lower() in ("1","true","yes","on"):
            print("🧪 FORCE_RC42_V1 -> exit(42)", flush=True)
            raise SystemExit(42)
    except SystemExit:
        raise
    except Exception:
        pass
    # --- /FORCE_RC42_V1 ---

    print("   ready_file=", READY_FILE)

    print("   jup_base=", JUP_BASE)

    print("   rpc_http=", RPC_HTTP)

    print("   input_mint=", SOL_MINT)

    print("   slippage_bps=", SLIPPAGE_BPS, "max_price_impact=", f"{MAX_PRICE_IMPACT_PCT}%")

    print("   one_shot=", ONE_SHOT, "dry_run=", DRY_RUN)

    # PHASE4_P4.4: detection regime marche (informatif, fail-open)
    global _current_regime
    try:
        _regime_result = _detect_regime()
        _current_regime = str(_regime_result.get("regime", "UNKNOWN"))
        print(f"   regime={_current_regime} score={_regime_result.get('regime_score', 0):.3f} conf={_regime_result.get('confidence', 0):.2f}", flush=True)
    except Exception as _re:
        _current_regime = "UNKNOWN"
        try:
            print(f"⚠️ regime detection failed (fail-open): {_re}", flush=True)
        except Exception:
            pass

    ready = _load_ready()
    # P1: pipeline counter — trace chaque étape de filtrage
    _pipeline_counts = {"loaded": len(ready), "ready_file": str(READY_FILE)}
    try:
        if READY_FILE.exists():
            _pipeline_counts["ready_file_size"] = READY_FILE.stat().st_size
            _pipeline_counts["ready_file_age_sec"] = int(time.time() - READY_FILE.stat().st_mtime)
    except Exception:
        pass
    print(f"   ready_loaded={len(ready)} file={READY_FILE}", flush=True)
    # HOLDINGS_FILTER_V1: remove held mints from ready early (before pick)
    try:
        holding_mints = set()
        # sources possibles: positions/open_positions/pos_list
        for _src in [locals().get('positions'), locals().get('open_positions'), locals().get('pos_list')]:
            if isinstance(_src, list):
                for _p in _src:
                    try:
                        _m = str(_p.get('mint') or _p.get('output_mint') or _p.get('token_mint') or '').strip()
                        if _m:
                            holding_mints.add(_m)
                    except Exception:
                        pass
        # holding cache (si présent)
        _hc = locals().get('holding_cache') or locals().get('_holding_cache')
        if isinstance(_hc, dict):
            for _m in list(_hc.keys()):
                try:
                    _m = str(_m).strip()
                    if _m:
                        holding_mints.add(_m)
                except Exception:
                    pass
        if holding_mints and isinstance(ready, list):
            _before = len(ready)
            for _m in holding_mints:
                ready = _drop_ready_mint(ready, _m)
            _after = len(ready)
            print(f"🧹 HOLDINGS_FILTER: ready {_before}->{_after} (held={len(holding_mints)})", flush=True)
    except Exception as _e:
        print("[WARN] HOLDINGS_FILTER failed:", _e, flush=True)
    _pipeline_counts["after_holdings"] = len(ready) if isinstance(ready, list) else -1
    # APPLY_RL_SKIP_INLINE (safe)

    # --- TRADER_RLSKIP_APPLY_V4 ---
    try:
        _before = len(ready) if isinstance(ready, list) else -1
        if isinstance(ready, list) and _before > 0:
            def _get_mint(x):
                try:
                    return (x.get('mint') or x.get('output_mint') or x.get('address') or '').strip()
                except Exception:
                    return ''
            ready = [x for x in ready if not _rl_skip_is_active(_get_mint(x))]
            _after = len(ready)
            if _after != _before:
                print(f"🧊 RL_SKIP filtered ready: {_before}->{_after} (file={os.getenv('RL_SKIP_FILE','state/rl_skip_mints.json')})", flush=True)
    except Exception as _e:
        print('rl_skip_filter_error:', _e, flush=True)
    # --- /TRADER_RLSKIP_APPLY_V4 ---

    # --- READY runtime filter (skip_file + rl_skip) ---
    try:
        _now = int(time.time())
    except Exception:
        _now = 0
    _skip_file = os.getenv("SKIP_MINTS_FILE", "state/skip_mints_trader.txt")
    _rl_file   = os.getenv("RL_SKIP_FILE", "state/rl_skip_mints.json")
    _skip_set = _load_skip_set(_skip_file)
    # purge expired + clamp before building the active skip set
    _rl_dict  = _rl_skip_purge_and_save(_rl_file, _now)
    _rl_set   = {m for m, v in _rl_dict.items() if int(v) > _now}
    if _skip_set or _rl_set:
        _in = len(ready)
        _ready_pre_rl = list(ready)
        def _ok_row(r):
            m = _row_mint(r)
            if not m:
                return False
            if m in _skip_set:
                return False
            if m in _rl_set:
                return False
            return True
        ready = [r for r in ready if _ok_row(r)]
        _out = len(ready)
        if _out != _in:
            print(f"🧊 RL_SKIP filtered ready (exec): in={_in} -> out={_out} skip={len(_skip_set)} rl={len(_rl_set)}")
        # RL_SKIP emptied all candidates: purge stale entries and retry once
        if _in > 0 and _out == 0 and _rl_set:
            print("[RL_SKIP] RL_SKIP_EMPTY_AFTER_FILTER: out=0 -> sleep and exit", flush=True)
            try:
                _s = float(os.getenv('EMPTY_READY_SLEEP_S','5'))
            except Exception:
                _s = 5.0
            time.sleep(max(0.0, _s))
            return 0
        if _out <= 0:
            print("⛔ no candidates after ready filter -> exit rc=0")
            return 0
    # --- end READY runtime filter ---
    _pipeline_counts["after_rl_skip"] = len(ready) if isinstance(ready, list) else -1

    # PHASE3_P3.3: ASSET_FILTER extrait vers core/asset_filter.filter_assets()
    from core.asset_filter import filter_assets as _filter_assets
    _before_af = len(ready) if isinstance(ready, list) else 0
    ready = _filter_assets(ready)
    _pipeline_counts["after_asset_filter"] = len(ready)
    if _before_af != len(ready):
        print(f"   asset_filter: {_before_af}->{len(ready)}", flush=True)
    print(f"   ready_count={len(ready)} pipeline={_pipeline_counts}", flush=True)

    if not ready:

        _write_err("no_ready_candidates", {"ready_file": READY_FILE})

        print("⚠️ ready_to_trade vide")
        # FIX5+P1: diagnostic détaillé dans decision_log quand ready=0
        _ready_diag = dict(_pipeline_counts)  # inclut loaded, after_holdings, after_rl_skip, after_asset_filter
        _ready_diag["ready_file"] = str(READY_FILE)
        _ready_diag["ready_file_exists"] = READY_FILE.exists() if hasattr(READY_FILE, 'exists') else False
        try:
            if READY_FILE.exists():
                _ready_diag["ready_file_size"] = READY_FILE.stat().st_size
                _ready_diag["ready_file_age_sec"] = int(time.time() - READY_FILE.stat().st_mtime)
                _ready_diag["ready_file_lines"] = sum(1 for _ in open(str(READY_FILE), "r", encoding="utf-8", errors="ignore"))
            else:
                _ready_diag["ready_file_size"] = 0
                _ready_diag["ready_file_age_sec"] = -1
                _ready_diag["ready_file_lines"] = 0
        except Exception as _e:
            _ready_diag["diag_error"] = str(_e)[:100]
        try:
            # Vérifier si d'autres ready files existent
            from pathlib import Path as _P
            _state = _P("state")
            if _state.exists():
                _candidates = [f.name for f in _state.iterdir()
                              if f.name.startswith("ready") and f.stat().st_size > 0]
                _ready_diag["other_ready_files"] = _candidates[:10]
        except Exception:
            pass
        _dtrace("SKIP", "", reason="no_ready_candidates", details=_ready_diag)
        print(f"   ready_diag={_ready_diag}", flush=True)

        return 0


    # IMPORTANT: trader_exec ne score PAS. Le scoring/filters doivent être upstream (core/trading.py)

    # pick first candidate not in skiplist (avoid getting stuck on ready[0])
    cand = None
    try:
        _skip = set()
        try:
            _skip = set(_load_skip_mints() or [])
        except Exception:
            _skip = set()
        for _c in ready:
            _m = (_c.get("outputMint") or _c.get("mint") or _c.get("address") or "").strip()
            if not _m:
                continue
            if _m in _skip:
                continue
            cand = _c
            break
    except Exception:
        cand = None

    if cand is None:
        cand = ready[0]

    output_mint = (cand.get("outputMint") or cand.get("mint") or cand.get("address") or "").strip()
# ANTI_REBUY_PICK_LOOP_V1
    # Re-pick if mint is skipped or last-buy cooldown blocks it
    skip_set = _load_skip_mints()
    if output_mint and (output_mint in skip_set or _is_last_buy_blocked(output_mint)):
        why = 'skip_file' if output_mint in skip_set else 'last_buy_cooldown'
        print(f"⚠️ re-pick: blocked by {why} mint={output_mint}")
        # remove blocked mints and pick again
        ready2 = [r for r in ready if (r.get('outputMint') or r.get('mint') or r.get('address') or '').strip() not in skip_set]
        cand2 = _pick_best_scored_ready(ready2) if USE_SCORED_IF_PRESENT else (ready2[0] if ready2 else None)
        if cand2:
            cand = cand2
            output_mint = (cand.get('outputMint') or cand.get('mint') or cand.get('address') or '').strip()
            print(f"   repick -> {output_mint}")
    FORCE_OUTPUT_MINT = os.getenv("FORCE_OUTPUT_MINT")
    if FORCE_OUTPUT_MINT:
        output_mint = FORCE_OUTPUT_MINT.strip()
        print(f"   [CFG] FORCE_OUTPUT_MINT -> {output_mint}")
    # --- DUAL_PROFILE_V1 ---
    if str(output_mint).lower().endswith("pump"):
        _profile = "PUMP"
        os.environ["HARD_SL_PCT"]   = "-0.35"
        os.environ["TP1_PCT"]       = "0.40"
        os.environ["TP2_PCT"]       = "1.00"
        os.environ["TIME_STOP_SEC"] = "600"
    else:
        _profile = "NORMAL"
        os.environ["HARD_SL_PCT"]   = "-0.20"
        os.environ["TP1_PCT"]       = "0.20"
        os.environ["TP2_PCT"]       = "0.50"
        os.environ["TIME_STOP_SEC"] = "1800"
    print(f"   [PROFILE] {_profile} mint={output_mint} HARD_SL_PCT={os.environ['HARD_SL_PCT']} TP1={os.environ['TP1_PCT']} TP2={os.environ['TP2_PCT']} TIME_STOP_SEC={os.environ['TIME_STOP_SEC']}", flush=True)
    # --- /DUAL_PROFILE_V1 ---
    # skiplist + bag check
    try:
        skip = _load_skip_mints()
        if output_mint in skip:
            print(f"⚠️ skip BUY: mint in SKIP_MINTS_FILE mint={output_mint}")
            _dtrace("SKIP", str(output_mint), reason="skip_mints_file", symbol=str(locals().get('output_symbol', '')))
            try:
                _sec = int(os.getenv('SKIPFILE_RLSKIP_SEC','600'))
            except Exception:
                _sec = 600
            try:
                _rl_skip_add(str(output_mint), int(_sec), reason='skip_file')
                print(f"🧊 RL_SKIP add (skip_file) mint={output_mint} sec={_sec}", flush=True)
            except Exception as _e:
                print("[WARN] RL_SKIP skip_file add failed:", _e, flush=True)
            return 0
    except Exception:
        pass
    if SKIP_IF_BAG:
        try:
            ui = float(_onchain_ui_balance_stable(str(output_mint), tries=3, sleep_s=0.4, timeout_s=3.5) or 0.0)
        except Exception as _e:
            ui = 0.0
            print(f"⚠️ holding ui fetch failed -> ui=0.0 err={_e}", flush=True)

        # if ui==0, recheck harder (avoid transient empty RPC)
        if ui <= 0.0:
            try:
                ui2 = float(_onchain_ui_balance_stable(str(output_mint), tries=6, sleep_s=0.5, timeout_s=6.0) or 0.0)
                if ui2 > 0.0:
                    ui = ui2
            except Exception as _e2:
                pass

        # update cache when we see ui>0
        if ui > 0.0:
            _holding_cache_update(str(output_mint), float(ui))
        else:
            # ui==0 : fallback to recent cache (safe: prevent accidental rebuy)
            _cached = _holding_cache_get_recent_ui(str(output_mint))
            if _cached > 0.0:
                print(f"🧠 holding cache used mint={output_mint} cached_ui={_cached}", flush=True)
                ui = float(_cached)

        IGNORE_DUST = float(os.getenv("IGNORE_HOLDING_BELOW", "0"))

        if ui < IGNORE_DUST:
            ui = 0.0

        if ui > 0.0:
            print(f"⚠️ skip BUY: already holding mint={output_mint} ui={ui}")
            _dtrace("SKIP", str(output_mint), reason="already_holding", symbol=str(locals().get('output_symbol', '')), details={"ui_balance": ui})
            _rl_skip_add(output_mint, int(os.getenv('HOLDING_SKIP_SEC','900')), reason='already_holding')
            if ui >= BAG_MIN_UI:
                print(f"🧷 autoskip already-holding DISABLED: RL_SKIP only mint={output_mint}", flush=True)
            else:
                print(f"   no autoskip: ui={ui} < BAG_MIN_UI={BAG_MIN_UI}", flush=True)
            if str(os.getenv('REPICK_ON_HOLDING','0')).strip() in ('1','true','True','yes','YES'):
                try:
                    _max = int(os.getenv('REPICK_MAX','5'))
                except Exception:
                    _max = 5
                try:
                    _depth = int(os.getenv('REPICK_DEPTH','0'))
                except Exception:
                    _depth = 0
                if _depth < _max:
                    try:
                        _append_skip_mint(str(output_mint))
                        print(f"🔁 REPICK (re-exec) depth={_depth+1}/{_max} -> skip mint={output_mint}", flush=True)
                        try:
                            _append_skip_mint(str(output_mint))
                            print(f"🧷 REPICK wrote skip mint={output_mint} -> {_skip_file_path()}", flush=True)
                        except Exception as _e:
                            print("[WARN] REPICK skip write failed:", _e, flush=True)
                    except Exception as _e:
                        print('repick autoskip failed:', _e, flush=True)
                    _env = os.environ.copy()
                    _env['REPICK_DEPTH'] = str(_depth + 1)
                    import sys as _sys
                    _env['SKIP_MINTS_FILE'] = str(os.getenv('SKIP_MINTS_FILE','')).strip() or str(globals().get('SKIP_MINTS_FILE','state/skip_mints_trader.txt'))
                    os.execve(_sys.executable, [_sys.executable] + _sys.argv, _env)
                else:
                    print(f"🧱 REPICK max reached depth={_depth}/{_max} -> stop", flush=True)
            return 0

    if not output_mint:

        _write_err("bad_candidate_no_mint", {"candidate": cand})

        print("⚠️ candidate sans mint/outputMint/address")

        return 0

    # rebuy cooldown
    try:
        import time as _time
        last = _load_last_buys()
        ts = int((last or {}).get(output_mint) or 0)
        if ts > 0:
            age = int(_time.time()) - ts
            if (not BYPASS_COOLDOWN) and age < BUY_COOLDOWN_S:
                wait = BUY_COOLDOWN_S - age
                print(f"   [COOLDOWN] selected mint={output_mint}")
                print(f"⚠️ skip BUY: rebuy cooldown mint={output_mint} age_s={age} wait_s={wait}")
                _dtrace("SKIP", str(output_mint), reason="rebuy_cooldown", details={"age_s": age, "wait_s": wait})
                # rebuy_cooldown_rl_skip
                try:
                    # 'wait' is computed just above: wait = BUY_COOLDOWN_S - age
                    _wait_s = int(wait) if 'wait' in locals() else int(os.getenv('COOLDOWN_S','1800'))
                except Exception:
                    _wait_s = int(os.getenv('COOLDOWN_S','1800'))
                # clamp (avoid nonsense)
                _wait_s = max(30, min(_wait_s, 6*3600))
                try:
                    _rl_skip_add(str(output_mint), sec=_wait_s, reason='rebuy_cooldown')
                    print(f"🧊 RL_SKIP rebuy_cooldown -> {output_mint} for {_wait_s}s (repick next)", flush=True)
                except Exception as _e:
                    print('rl_skip_add rebuy_cooldown failed:', _e, flush=True)
                return 0
    except Exception:
        pass



    amount_lamports = _lamports_from_any(cand.get("amount_lamports"))
    BUY_LAMPORTS_OVERRIDE = os.getenv("BUY_LAMPORTS")
    if BUY_LAMPORTS_OVERRIDE:
        # --- RL_SKIP REPICK BEFORE PRINT (auto) ---
        try:
            _rl = _rl_skip_load() or {}
            _now = int(_t.time())
            _until = int(_rl.get(output_mint, 0) or 0)
            if output_mint and _until > _now:
                _old = output_mint
                _cands = list(ready) if isinstance(ready, (list, tuple)) else []
                try:
                    _cands.sort(key=lambda d: (d.get('score') if isinstance(d, dict) else -1), reverse=True)
                except Exception:
                    pass
                _new = None
                for _c in _cands:
                    if not isinstance(_c, dict):
                        continue
                    _m = _c.get('mint') or _c.get('address') or _c.get('token')
                    if not isinstance(_m, str) or not _m.strip():
                        continue
                    _m = _m.strip()
                    try:
                        _u = int(_rl.get(_m, 0) or 0)
                    except Exception:
                        _u = 0
                    if _u <= _now:
                        _new = _c
                        break
                if _new is not None:
                    output_mint = (_new.get('mint') or _new.get('address') or _new.get('token') or output_mint)
                    if isinstance(output_mint, str):
                        output_mint = output_mint.strip() or _old
                    print(f"🧊 RL_SKIP repick(before print): {_old} -> {output_mint}", flush=True)
        except Exception as _e:
            print(f"rl_skip repick(before print) failed: {_e}", flush=True)
    # --- amount_lamports guard (v2) ---
    if amount_lamports is None:
        _buy_sol = os.environ.get("BUY_AMOUNT_SOL", "").strip()
        _buy_lam = os.environ.get("BUY_AMOUNT_LAMPORTS", "").strip() or os.environ.get("AMOUNT_LAMPORTS", "").strip()
        try:
            if _buy_sol:
                amount_lamports = int(float(_buy_sol) * 1_000_000_000)
            elif _buy_lam:
                amount_lamports = int(_buy_lam)
        except Exception:
            amount_lamports = None
    
    if not amount_lamports or int(amount_lamports) <= 0:
        print(f"⛔ amount_lamports invalid: {amount_lamports} (set BUY_AMOUNT_SOL or BUY_AMOUNT_LAMPORTS)")
        _dtrace("REJECT", str(output_mint), reason="amount_lamports_invalid")
        return 0
    # --- /amount_lamports guard (v2) ---
    print(f"   pick= {output_mint} amount_lamports= {amount_lamports}", flush=True)
    # --- HIST_BAD_HOOK_APPLIED_V2 ---
    try:
        _hs, _hmsg, _hn, _havg, _hsec = _hist_bad_should_skip(output_mint)
        if _hs:
            print(_hmsg, flush=True)
            _dtrace("SKIP", str(output_mint), reason="hist_bad", details={"n_closed": _hn, "avg_pnl": _havg, "skip_sec": _hsec})
            # Prefer RL_SKIP if available, else fallback to SKIP_MINTS_FILE
            try:
                _rl_skip_add(output_mint, int(_hsec), reason='hist_bad')
                print('🧊 RL_SKIP hist_bad sec=%d mint=%s' % (int(_hsec), output_mint), flush=True)
            except Exception as _e:
                try:
                    import os as _os
                    _sf = str(_os.getenv('SKIP_MINTS_FILE','state/skip_mints_trader.txt')).strip()
                    if _sf:
                        with open(_sf,'a',encoding='utf-8') as _f: _f.write(output_mint.strip()+'\n')
                        print('🧷 SKIP_MINTS fallback hist_bad -> %s' % _sf, flush=True)
                except Exception:
                    pass
            return 0
    except Exception as _e:
        print('hist_hook_error:', _e, flush=True)
    # --- /HIST_BAD_HOOK_APPLIED_V2 ---

    # --- LOW_SOL_GUARD_V5 ---
    import os as _os

    _wallet = _os.getenv("WALLET_PUBKEY") or _os.getenv("TRADER_USER_PUBLIC_KEY") or None
    _rpc = _os.getenv("RPC_HTTP", "https://api.mainnet-beta.solana.com")

    def _fenv(name, default):
        try:
            v = _os.getenv(name, "")
            return float(v) if str(v).strip() != "" else float(default)
        except Exception:
            return float(default)

    # always read from env (do not trust in-code constants)
    _buf = _fenv("MIN_SOL_BUFFER_SOL", 0.0)
    _amt = _fenv("BUY_AMOUNT_SOL", (float(amount_lamports)/1_000_000_000 if amount_lamports else 0.0))
    _extra = _fenv("BUY_EXTRA_SOL_CUSHION", 0.003)
    _need = _buf + _amt + _extra

    # resolve SOL balance: locals -> RPC getBalance(wallet)
    _sol = None
    try:
        _loc = locals()
        if "sol_balance_sol" in _loc and _loc["sol_balance_sol"] is not None:
            _sol = float(_loc["sol_balance_sol"])
        elif "sol_balance_lamports" in _loc and _loc["sol_balance_lamports"] is not None:
            _sol = float(_loc["sol_balance_lamports"]) / 1_000_000_000
        elif "sol_lamports" in _loc and _loc["sol_lamports"] is not None:
            _sol = float(_loc["sol_lamports"]) / 1_000_000_000
        elif "sol_balance" in _loc and _loc["sol_balance"] is not None:
            _sol = float(_loc["sol_balance"])
    except Exception:
        _sol = None

    if _sol is None and _wallet:
        try:
            import requests as _rq
            _r = _rq.post(_rpc, json={"jsonrpc":"2.0","id":1,"method":"getBalance","params":[str(_wallet)]}, timeout=10)
            if _r.status_code == 200:
                _j = _r.json()
                _lam = (((_j or {}).get("result") or {}).get("value"))
                if _lam is not None:
                    _sol = float(_lam) / 1_000_000_000
        except Exception:
            pass

    print(f"LOW_SOL_GUARD status sol={_sol} need={_need:.6f} (buf={_buf:.6f} amt={_amt:.6f} extra={_extra:.6f}) wallet={_wallet} rpc={_rpc}", flush=True)

    if _sol is not None and _sol < _need:
        print(f"LOW_SOL_GUARD SKIP sol={_sol:.6f} need>={_need:.6f}", flush=True)
        _dtrace("SKIP", str(output_mint), reason="low_sol_guard", details={"sol_balance": _sol, "sol_needed": _need})
        try:
            _rl_skip_add(output_mint, 600, reason="low_sol_guard")
        except Exception:
            pass
        import sys
        sys.exit(0)
# --- /LOW_SOL_GUARD_V5 ---

    if TRADER_QUOTE_ONLY:
        # quote-only: perform 1 Jupiter quote (exercise RL + cache), then stop

        import asyncio as _asyncio

        import aiohttp as _aiohttp

        from core.jupiter_exec import _get_json as _jup_get_json

        _jup_base = os.getenv('JUP_BASE_URL', 'https://lite-api.jup.ag').rstrip('/')

        _qurl = f"{_jup_base}/swap/v1/quote"

        _qparams = {

          'inputMint': SOL_MINT,

          'outputMint': output_mint,

          'amount': str(amount_lamports),

          'slippageBps': str(SLIPPAGE_BPS),

        }

        async def _qo():

          async with _aiohttp.ClientSession() as _s:

            return await _jup_get_json(_s, _qurl, _qparams)

        try:

          _q = _asyncio.run(_qo())

          _rp = _q.get('routePlan') or []

          print(f"🧪 quote_only quote OK outAmount={_q.get('outAmount')} routes={len(_rp)}", flush=True)

        except Exception as _e:

          print(f"🧪 quote_only quote ERR {type(_e).__name__} {str(_e)[:140]}", flush=True)

        return 0

    # PHASE4_P4.5: scoring elite multi-composantes (0-100, explicable)
    _elite_score = {}
    try:
        from core.scoring_elite import score_candidate_elite
        _elite_score = score_candidate_elite(cand, str(output_mint), regime=_current_regime)
        # Gate optionnel (SCORE_MIN_BUY=0 par defaut = desactive)
        if not _elite_score.get("gate_pass", True):
            _sc = _elite_score.get("score_total", 0)
            _dtrace("REJECT", str(output_mint), reason=f"score_too_low:{_sc:.0f}",
                    symbol=str(locals().get('output_symbol', '')),
                    score_total=_sc,
                    score_market=_elite_score.get("components", {}).get("market", 0),
                    score_flow=_elite_score.get("components", {}).get("flow", 0),
                    score_history=_elite_score.get("components", {}).get("history", 0),
                    score_dev=_elite_score.get("components", {}).get("dev", 0),
                    score_risk=_elite_score.get("components", {}).get("risk", 0),
                    score_execution=_elite_score.get("components", {}).get("execution", 0),
                    regime=_current_regime)
            return 0
    except Exception as _se:
        try:
            print(f"⚠️ scoring_elite failed (fail-open): {_se}", flush=True)
        except Exception:
            pass
    # --- /PHASE4_P4.5 ---

    # PHASE3_P3.4: security gate extrait vers core/security_gate.py
    from core.security_gate import check_max_positions, check_antirug
    _gate_ok, _gate_msg = check_max_positions()
    if not _gate_ok:
        _dtrace("REJECT", str(output_mint), reason="max_open_positions", symbol=str(locals().get('output_symbol', '')), regime=_current_regime)
        return 0
    _ar_ok, _ar_msg, _ar_skip = check_antirug(str(output_mint))
    if not _ar_ok:
        _dtrace("REJECT", str(output_mint), reason=f"antirug:{_ar_skip or 'block'}", symbol=str(locals().get('output_symbol', '')), regime=_current_regime)
        if _ar_skip:
            try:
                _rl_skip_add(str(output_mint), reason=_ar_skip)
            except Exception:
                pass
        return 0
    # --- /PHASE3_P3.4 ---

    # PHASE4_P4.3: risk engine circuit breaker (avant QUOTE)
    try:
        from core.risk_engine import check_circuit_breaker
        _cb_ok, _cb_reason = check_circuit_breaker()
        if not _cb_ok:
            print(f"🛑 CIRCUIT_BREAKER → BUY bloqué: {_cb_reason}", flush=True)
            _dtrace("REJECT", str(output_mint), reason=f"circuit_breaker:{_cb_reason[:80]}", symbol=str(locals().get('output_symbol', '')), regime=_current_regime)
            return 0
    except Exception as _cb_e:
        # Fail-open: si risk_engine indisponible, on continue
        try:
            print(f"⚠️ risk_engine.check_circuit_breaker import/call failed (fail-open): {_cb_e}", flush=True)
        except Exception:
            pass
    # --- /PHASE4_P4.3 ---

    # PHASE4_P4.6: sizing advisor (ajustement dynamique du montant)
    _sizing_result = {}
    try:
        _sizing_enabled = os.getenv("SIZING_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
        if _sizing_enabled:
            from core.sizing_advisor import compute_sizing
            _score_for_sizing = float(_elite_score.get("score_total", 0)) if _elite_score else 0.0
            _base_sol = float(amount_lamports) / 1_000_000_000 if amount_lamports else 0.0
            _sizing_result = compute_sizing(
                score_total=_score_for_sizing,
                regime=_current_regime,
                base_sol=_base_sol,
            )
            # Appliquer le sizing recommande
            _new_lamports = int(_sizing_result.get("recommended_lamports", amount_lamports))
            if _new_lamports > 0:
                amount_lamports = _new_lamports
                print(f"   sizing_applied: {amount_lamports} lamports ({_sizing_result.get('recommended_sol', 0):.4f} SOL)", flush=True)
        else:
            print("   sizing=OFF (set SIZING_ENABLED=1 to activate)", flush=True)
    except Exception as _sz_e:
        try:
            print(f"⚠️ sizing_advisor failed (fail-open, using base amount): {_sz_e}", flush=True)
        except Exception:
            pass
    # --- /PHASE4_P4.6 ---

    # ============================================================
    # P4: BUY QUALITY GATES (avant quote) — reject tokens de mauvaise qualité
    # ============================================================
    # Configurable via env vars, fail-open (si check echoue, on continue)
    try:
        _p4_enabled = os.getenv("P4_BUY_GATES_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
        if _p4_enabled:
            # P4.1: Reject tokens trop vieux (age en secondes depuis le fichier ready)
            _p4_max_age = int(os.getenv("P4_MAX_TOKEN_AGE_SEC", "3600"))
            try:
                _cand_ts = int(cand.get("ts", 0) or 0)
                if _cand_ts > 0:
                    _cand_age = int(time.time()) - _cand_ts
                    if _cand_age > _p4_max_age:
                        print(f"⚠️ P4_REJECT: token too old age={_cand_age}s max={_p4_max_age}s mint={output_mint}", flush=True)
                        _dtrace("REJECT", str(output_mint), reason=f"p4_too_old:{_cand_age}s",
                                symbol=str(locals().get('output_symbol', '')),
                                score_total=float(_elite_score.get("score_total", 0)) if _elite_score else 0.0,
                                details={"age_sec": _cand_age, "max_age": _p4_max_age, "candidate_source": str(cand.get("source", "ready"))})
                        _rl_skip_add(str(output_mint), reason="p4_too_old")
                        return 0
            except Exception:
                pass

            # P4.2: Reject tokens sans route Jupiter (pre-check via champ du candidat)
            _p4_jup_check = os.getenv("P4_REQUIRE_JUPITER_ROUTE", "0").strip().lower() in ("1", "true", "yes")
            if _p4_jup_check:
                try:
                    _jup_route = cand.get("jupiter_route", cand.get("jup_routable"))
                    if _jup_route is False:
                        _jup_reason = str(cand.get("jup_reason", cand.get("details", {}).get("jup_reason", "no_route")))
                        print(f"⚠️ P4_REJECT: no Jupiter route reason={_jup_reason} mint={output_mint}", flush=True)
                        _dtrace("REJECT", str(output_mint), reason=f"p4_no_jupiter_route:{_jup_reason}",
                                symbol=str(locals().get('output_symbol', '')),
                                score_total=float(_elite_score.get("score_total", 0)) if _elite_score else 0.0,
                                details={"jup_reason": _jup_reason, "candidate_source": str(cand.get("source", "ready"))})
                        _rl_skip_add(str(output_mint), reason="p4_no_route")
                        return 0
                except Exception:
                    pass

            # P4.3: Reject tokens avec price impact trop élevé (champ du candidat)
            _p4_max_impact = float(os.getenv("P4_MAX_PRICE_IMPACT_PCT", "10.0"))
            try:
                _cand_impact = float(cand.get("price_impact_estimate",
                                cand.get("jup_price_impact_pct",
                                cand.get("details", {}).get("jup_price_impact_pct", -1))) or -1)
                if _cand_impact > 0 and _cand_impact > _p4_max_impact:
                    print(f"⚠️ P4_REJECT: high price impact={_cand_impact:.1f}% max={_p4_max_impact}% mint={output_mint}", flush=True)
                    _dtrace("REJECT", str(output_mint), reason=f"p4_high_impact:{_cand_impact:.1f}%",
                            symbol=str(locals().get('output_symbol', '')),
                            score_total=float(_elite_score.get("score_total", 0)) if _elite_score else 0.0,
                            details={"impact_pct": _cand_impact, "max_impact": _p4_max_impact, "candidate_source": str(cand.get("source", "ready"))})
                    _rl_skip_add(str(output_mint), reason="p4_high_impact")
                    return 0
            except Exception:
                pass

            # P4.4: Reject tokens avec liquidité trop faible
            _p4_min_liq = float(os.getenv("P4_MIN_LIQUIDITY_USD", "1000"))
            try:
                _cand_liq = float(cand.get("liquidity_usd", cand.get("_liq_usd", 0)) or 0)
                if _cand_liq > 0 and _cand_liq < _p4_min_liq:
                    print(f"⚠️ P4_REJECT: low liquidity=${_cand_liq:.0f} min=${_p4_min_liq:.0f} mint={output_mint}", flush=True)
                    _dtrace("REJECT", str(output_mint), reason=f"p4_low_liq:{_cand_liq:.0f}",
                            symbol=str(locals().get('output_symbol', '')),
                            score_total=float(_elite_score.get("score_total", 0)) if _elite_score else 0.0,
                            details={"liq_usd": _cand_liq, "min_liq": _p4_min_liq, "candidate_source": str(cand.get("source", "ready"))})
                    _rl_skip_add(str(output_mint), reason="p4_low_liq")
                    return 0
            except Exception:
                pass

            # P4.5: Log des raisons d'achat (reason_buy) — P5 observabilité
            try:
                _reason_buy_parts = []
                _cand_src = str(cand.get("source", cand.get("_source", "ready")))
                _cand_score = float(cand.get("score_total", cand.get("score", 0)) or 0)
                _cand_liq_log = float(cand.get("liquidity_usd", cand.get("_liq_usd", 0)) or 0)
                _cand_vol = float(cand.get("vol_5m", cand.get("volume_5m_usd", 0)) or 0)
                _reason_buy_parts.append(f"src={_cand_src}")
                _reason_buy_parts.append(f"score={_cand_score:.0f}")
                if _cand_liq_log > 0:
                    _reason_buy_parts.append(f"liq=${_cand_liq_log:.0f}")
                if _cand_vol > 0:
                    _reason_buy_parts.append(f"vol5m=${_cand_vol:.0f}")
                print(f"   P4_BUY_REASON: {' '.join(_reason_buy_parts)} mint={output_mint}", flush=True)
            except Exception:
                pass

    except Exception as _p4e:
        try:
            print(f"⚠️ P4 buy gates failed (fail-open): {_p4e}", flush=True)
        except Exception:
            pass
    # --- /P4 BUY QUALITY GATES ---

    # QUOTE
    qurl = os.getenv("JUP_QUOTE_URL", f"{JUP_BASE}/swap/v1/quote")
    params = {
        "inputMint": SOL_MINT,
        "outputMint": output_mint,
        "amount": str(int(amount_lamports)),
        "slippageBps": str(SLIPPAGE_BPS),
    }
    try:
        qr = requests.get(qurl, params=params, headers=_headers(), timeout=25)
        _append_dbg("QUOTE_URL=" + qr.url)
        _append_dbg("QUOTE_STATUS=" + str(qr.status_code))
        _append_dbg("QUOTE_BODY=" + (qr.text[:2000] if qr.text else ""))
        if qr.status_code != 200:
            _write_err("quote_http", {"status": qr.status_code, "text": qr.text[:2000], "url": qr.url})
            print("❌ quote failed http=", qr.status_code)
            _dtrace("REJECT", str(output_mint), reason=f"quote_http_{qr.status_code}", symbol=str(locals().get('output_symbol', '')),
                    score_total=float(_elite_score.get("score_total", 0)) if _elite_score else 0.0,
                    details={"http_status": qr.status_code})
            # --- RL_SKIP_ON_429 ---
            try:
                _h = int(qr.status_code)
            except Exception:
                _h = -1
            if _h == 429:
                # PERF: rate-limit => RL_SKIP + repick next tick
                try:
                    _rl_skip_add(str(output_mint), reason='quote_429')
                except Exception as _e:
                    print('rl_skip_add failed:', _e, flush=True)
                try:
                    print(f"🧊 RL_SKIP quote_429 -> {output_mint} for {RL_SKIP_SEC}s (repick next)", flush=True)
                    import time as _t
                    _b = int(os.getenv('QUOTE_429_BACKOFF_S','25'))
                    print(f'⏳ 429 backoff sleep={_b}s', flush=True)
                    _t.sleep(max(1, _b))
                except Exception:
                    pass
                import time as _time
                _time.sleep(float(os.getenv('QUOTE_429_SLEEP_S','0.3')))
                raise SystemExit(42)
            # PHASE3_P3.5: 3 blocs AUTO_SKIP quasi-identiques fusionnés en 1 seul
            # (AUTO_SKIP_QUOTE_HTTP_FAIL_V2, AUTO_SKIP_QUOTE_HTTP_400_V1, AUTO_SKIP_NO_ROUTE)
            # 429 est déjà géré ci-dessus par SystemExit(42) → ici on ne traite que les erreurs non-429
            try:
                _body = (qr.text or '')
                _low = _body.lower()
                print('   quote_body_head=', _body[:500])
                # TOKEN_NOT_TRADABLE / no route => autoskip (éviter de boucler sur ce mint)
                if ('token_not_tradable' in _low) or ('not tradable' in _low) or ('could not find any route' in _low) or ('no_route' in _low) or ('no route' in _low):
                    try:
                        _append_skip_mint(str(output_mint))
                        print(f'⛔ AUTO_SKIP_QUOTE_FAIL mint={output_mint} -> {SKIP_MINTS_FILE}', flush=True)
                    except Exception as _e:
                        print(f'autoskip quote-fail failed: {_e}', flush=True)
                else:
                    print('ℹ️ quote failed but not NO_ROUTE/NOT_TRADABLE -> no autoskip', flush=True)
            except Exception as _e:
                print(f'⚠️ AUTO_SKIP handler error mint={output_mint} err={repr(_e)}', flush=True)
            return 0
        quote = qr.json()
    except Exception as e:
        _write_err("quote_exc", {"error": str(e)})
        print("❌ quote exception:", e)
        _dtrace("REJECT", str(output_mint), reason="quote_exception", symbol=str(locals().get('output_symbol', '')),
                score_total=float(_elite_score.get("score_total", 0)) if _elite_score else 0.0,
                details={"error": str(e)[:200]})
        return 0

    # SWAP build
    surl = os.getenv("JUP_SWAP_URL", f"{JUP_BASE}/swap/v1/swap")
    body = {"quoteResponse": quote, "userPublicKey": WALLET_PUBKEY, "wrapAndUnwrapSol": True}

    try:
        sr = requests.post(surl, headers=_headers(), json=body, timeout=35)
        _append_dbg("SWAP_STATUS=" + str(sr.status_code))
        _append_dbg("SWAP_BODY=" + (sr.text[:2000] if sr.text else ""))
        if sr.status_code != 200:
            _write_err("swap_http", {"status": sr.status_code, "text": sr.text[:2000]})
            print("❌ swap build failed http=", sr.status_code)
            _dtrace("REJECT", str(output_mint), reason=f"swap_http_{sr.status_code}", symbol=str(locals().get('output_symbol', '')),
                    score_total=float(_elite_score.get("score_total", 0)) if _elite_score else 0.0,
                    details={"http_status": sr.status_code})
            try:
                _raw = sr
                _code = getattr(_raw, 'status_code', _raw)
                if str(_code).strip() == '429':
                    print('🧊 BUY_429_DETECTED swap_build -> exit(42)', flush=True)
                    raise SystemExit(42)
            except SystemExit:
                raise
            except Exception:
                pass
            return 0

        swap = sr.json()
        txb64 = swap.get("swapTransaction")
        if not txb64:
            _write_err("swap_no_tx", {"keys": list(swap.keys()), "sample": swap})
            print("⚠️ swap response sans swapTransaction")
            _dtrace("REJECT", str(output_mint), reason="swap_no_tx", symbol=str(locals().get('output_symbol', '')),
                    score_total=float(_elite_score.get("score_total", 0)) if _elite_score else 0.0)
            return 0

        OUT_TX_B64.write_text(txb64, encoding="utf-8")
        OUT_META.write_text(json.dumps({
            "ts": int(_time.time()),
            "mode": "BUY",
            "inputMint": SOL_MINT,
            "outputMint": output_mint,
            "amount_lamports": amount_lamports,
            "slippageBps": SLIPPAGE_BPS,
            "userPublicKey": WALLET_PUBKEY,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        if TRADER_QUOTE_ONLY:

            print("🧪 quote_only -> skip built tx", flush=True)

            return 0

        print("✅ built tx -> last_swap_tx.b64")
        # STOP_AFTER_BUILD_ALWAYS_V1: if STOP_AFTER_BUILD_TX=1, EXIT after build (NO SEND), even in LIVE
        if os.getenv('STOP_AFTER_BUILD_TX','0').strip().lower() in ('1','true','yes','on'):
            print('🛑 STOP_AFTER_BUILD_TX=1 -> EXIT after build (NO SEND)', flush=True)
            # RC3_AFTER_BUILD_V1: signal parent loop that we built a tx (DRY-ish)
            raise SystemExit(3)
        # STOP_AFTER_BUILD_TX (avoid spamming quotes/swaps in DRY)
        try:
            _is_dry = os.getenv('TRADER_DRY_RUN','0').strip().lower() in ('1','true','yes','on')
        except Exception:
            _is_dry = False
        # AUTO_SKIP_AFTER_BUILD_TX (perf)
        # --- DRYRUN_BUILDTX_RL_SKIP_HOOK_V3 ---
        # In DRY_RUN, optionally add short RL_SKIP to rotate candidates after building a tx.
        try:
            _is_dry = (os.getenv('TRADER_DRY_RUN','0').strip().lower() in ('1','true','yes','on'))
        except Exception:
            _is_dry = False
        if _is_dry:
            try:
                _sec = int(float(os.getenv('DRYRUN_BUILDTX_RL_SKIP_SEC','0')))
            except Exception:
                _sec = 0
            if _sec > 0:
                try:
                    _rl_skip_add(str(output_mint), sec=_sec, reason='dryrun_built_tx')
                except Exception as _e:
                    print(f"rl_skip_add(dryrun_built_tx) failed: {_e}", flush=True)
        else:
            # LIVE: keep existing behavior (mark built_tx) but don't crash if rl_skip isn't available
            try:
                _rl_skip_add(str(output_mint), reason='built_tx')
            except Exception:
                pass
        # --- /DRYRUN_BUILDTX_RL_SKIP_HOOK_V3 ---
        if DRY_RUN:
            print("🧪 DRY_RUN=1 -> not sending")
            # --- AUTO_SKIP_DRY_RUN_V2 ---
            try:
                if str(os.getenv('TRADER_DRY_RUN','0')).strip().lower() in ('1','true','yes','on'):
                    _m = str(output_mint or '').strip()
                    _sf = str(_os.getenv('SKIP_MINTS_FILE','state/skip_mints_trader.txt')).strip()
                    if _m and _sf:
                        _seen = False
                        try:
                            if os.path.exists(_sf):
                                with open(_sf, 'r', encoding='utf-8', errors='ignore') as _rf:
                                    for _ln in _rf:
                                        if _ln.strip() == _m:
                                            _seen = True
                                            break
                        except Exception:
                            _seen = False
                        if not _seen:
                            try:
                                os.makedirs(os.path.dirname(_sf) or '.', exist_ok=True)
                            except Exception:
                                pass
                            try:
                                if str(os.getenv('DRYRUN_AUTOSKIP','0')).strip() in ('1','true','True','yes','YES'):
                                    with open(_sf, 'a', encoding='utf-8') as _af:
                                        _af.write(_m + '\n')
                                else:
                                    print("🧷 DRY_RUN autoskip disabled (set DRYRUN_AUTOSKIP=1 to enable)")
                                if _in_rebuy_pool(output_mint):
                                    print(f"🧪 REBUY_POOL allow mint={output_mint} (no autoskip)", flush=True)
                                else:
                                    if str(os.getenv('DRYRUN_AUTOSKIP','0')).strip() in ('1','true','True','yes','YES'):
                                        print(f"🧷 DRY_RUN autoskip -> {_m} (SKIP_MINTS_FILE={_sf})", flush=True)
                            except Exception:
                                pass
            except Exception:
                pass
            # --- /AUTO_SKIP_DRY_RUN_V2 ---

            # --- DRY_RUN_AUTOSKIP_SLEEP_V1 ---
            try:
                if str(os.getenv('TRADER_DRY_RUN','0')).strip().lower() in ('1','true','yes','on'):
                    _s = float(os.getenv('DRY_RUN_AUTOSKIP_SLEEP_S','0.75') or 0.75)
                    if _s > 0:
                        time.sleep(_s)
            except Exception:
                pass
            # --- /DRY_RUN_AUTOSKIP_SLEEP_V1 ---

            return 0

        try:
            txsig = _send_signed_b64(txb64, RPC_HTTP)
            OUT_SENT.write_text(json.dumps({"ts": int(_time.time()), "txsig": txsig}, ensure_ascii=False, indent=2), encoding="utf-8")
            print("✅ sent txsig=", txsig)
            # PHASE4_P4.2+P4.5: trace BUY réussi avec score elite breakdown
            try:
                _buy_sym = str(locals().get('output_symbol') or locals().get('out_symbol') or locals().get('symbol') or '')
                _buy_sol = float(_sizing_result.get("recommended_sol", 0)) if _sizing_result else float(amount_lamports) / 1_000_000_000
                _comp = _elite_score.get("components", {}) if _elite_score else {}
                _buy_score = float(_elite_score.get("score_total", 0)) if _elite_score else float(locals().get('_cand_score') or 0.0)
                # P5: enrichissement details avec source, pipeline_counts, reason_buy
                _p5_details = {
                    "txsig": str(txsig)[:16],
                    "explain": str(_elite_score.get("explain", ""))[:100],
                }
                try:
                    _p5_details["candidate_source"] = str(cand.get("source", cand.get("_source", "ready")))
                    _p5_details["pipeline_counts"] = dict(_pipeline_counts) if '_pipeline_counts' in dir() else {}
                    _p5_details["score_components"] = dict(cand.get("score_components", {}))
                    _p5_details["reason_buy"] = f"src={_p5_details['candidate_source']} score={_buy_score:.0f} sol={_buy_sol:.4f}"
                    _p5_details["liquidity_usd"] = float(cand.get("liquidity_usd", cand.get("_liq_usd", 0)) or 0)
                    _p5_details["risk_flags"] = cand.get("risk_flags", [])
                    _p5_details["jupiter_route"] = cand.get("jupiter_route", cand.get("jup_routable"))
                except Exception:
                    pass
                _dtrace("BUY", str(output_mint), reason="tx_sent", symbol=_buy_sym,
                        score_total=_buy_score, sizing_sol=_buy_sol,
                        score_market=float(_comp.get("market", 0)),
                        score_flow=float(_comp.get("flow", 0)),
                        score_history=float(_comp.get("history", 0)),
                        score_dev=float(_comp.get("dev", 0)),
                        score_risk=float(_comp.get("risk", 0)),
                        score_execution=float(_comp.get("execution", 0)),
                        regime=_current_regime,
                        details=_p5_details)
            except Exception:
                pass
            # --- DB record BUY (schema-safe) ---
            # DB_GUARD_DRY_V1: avoid polluting DB in DRY_RUN / STOP_AFTER_BUILD_TX
            if os.getenv('TRADER_DRY_RUN','0').strip().lower() in ('1','true','yes','on') or os.getenv('STOP_AFTER_BUILD_TX','0').strip().lower() in ('1','true','yes','on'):
                print('🧪 DB_GUARD_DRY_V1 -> skip DB record (dry/stop_after_build)', flush=True)
            else:
                try:
                    _dbp = os.getenv('TRADES_DB_PATH', os.getenv('DB_PATH', 'state/trades.sqlite'))
                    _sym = locals().get('output_symbol') or locals().get('out_symbol') or locals().get('symbol') or ''
                    _qty_sol = float(locals().get('amount_sol') or locals().get('buy_amount_sol') or 0.0)
                    _price = float(locals().get('exec_price') or locals().get('price') or 0.0)
                    _db_record_buy_schema_safe(_dbp, output_mint, txsig, symbol=_sym, qty_token=0.0, price=_price, qty_sol=_qty_sol)
                    print(f"✅ DB: recorded BUY mint={output_mint} txsig={txsig[:8]}… db={_dbp}", flush=True)
                except Exception as _e:
                    print(f"⚠️ DB record BUY failed: {_e}", flush=True)

            # PHASE3_P3.2: resync inline extrait vers core/qty_resync.resync_buy_inline()
            # Couche 1: resync_buy_inline (ici), Couche 2: scripts/resync_buy_qty.py, Couche 3: sell_engine
            resync_buy_inline(str(output_mint), txsig)

            # ANTI_REBUY_AFTER_SEND_V1
            try:
                _last_buy_set(output_mint)
            except Exception:
                pass

            # autoskip: éviter rebuy du même mint après BUY OK
            try:
                if output_mint:
                    _autoskip_mint(output_mint)
            except Exception as e:
                print('⚠️ autoskip failed:', e)
            # EXIT2_AFTER_SEND_V1: signal parent loop that a swap was sent
            raise SystemExit(2)
            # PHASE1_P1.3: supprimé code mort après raise SystemExit(2) (record_last_buy inaccessible)


        except Exception as e:
            _write_err("send_exc", {"error": str(e)})
            print("❌ send exception:", e)
            _dtrace("REJECT", str(output_mint), reason="send_exception", symbol=str(locals().get('output_symbol', '')),
                    score_total=float(_elite_score.get("score_total", 0)) if _elite_score else 0.0,
                    details={"error": str(e)[:200]})

        return 0

    except Exception as e:
        _write_err("swap_exc", {"error": str(e)})
        print("❌ swap exception:", e)
        _dtrace("REJECT", str(output_mint), reason="swap_exception", symbol=str(locals().get('output_symbol', '')),
                score_total=float(_elite_score.get("score_total", 0)) if _elite_score else 0.0,
                details={"error": str(e)[:200]})
        return 0


if __name__ == "__main__":
    # --- QUOTE_429_RC42_MINWRAP_V1 ---
    try:
        raise SystemExit(main())
    except Exception as e:
        msg = str(e)
        if ('quote failed http= 429' in msg) or ('http= 429' in msg and 'quote' in msg):
            print('❌ quote failed http= 429', flush=True)
            sys.exit(42)
        raise
    # --- /QUOTE_429_RC42_MINWRAP_V1 ---
