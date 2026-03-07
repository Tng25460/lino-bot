import os, json, time, sqlite3, statistics
from typing import Dict, Any, List, Tuple, Optional
import os
import json
import time


# --- BRAIN_HIST_GOOD_LOADER_V1 ---
def _hist_good_boost_map(db_path: str):
    """Return {mint: (n_closed, avg_pnl, last_close_ts)} from brain sqlite mint_hist."""
    import sqlite3
    out = {}
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        for mint, n_closed, avg_pnl, last_ts in cur.execute(
            "SELECT mint, n_closed, avg_pnl, last_close_ts FROM mint_hist"
        ):
            m = str(mint).strip()
            if not m:
                continue
            out[m] = (int(n_closed or 0), float(avg_pnl or 0.0), int(last_ts or 0))
    except Exception:
        return {}
    try:
        con.close()
    except Exception:
        pass
    return out
# --- /BRAIN_HIST_GOOD_LOADER_V1 ---

# --- BRAIN_HIST_GOOD_BOOST_V1 ---
def _hist_good_lookup(mint: str):
    """
    Return (n_closed:int, avg_pnl:float) for mint from brain.sqlite.
    Cached per-process (loads map once).
    """
    import os
    import sqlite3
    from functools import lru_cache

    db_path = os.getenv("BRAIN_DB_PATH", "state/brain.sqlite")

    @lru_cache(maxsize=1)
    def _load_map(_db_path: str):
        out = {}
        try:
            con = sqlite3.connect(_db_path)
            cur = con.cursor()
            for m, n_closed, avg_pnl in cur.execute("SELECT mint, n_closed, avg_pnl FROM mint_hist"):
                mm = (m or "").strip()
                if not mm:
                    continue
                try:
                    n = int(n_closed or 0)
                except Exception:
                    n = 0
                try:
                    ap = float(avg_pnl or 0.0)
                except Exception:
                    ap = 0.0
                out[mm] = (n, ap)
            con.close()
        except Exception:
            return {}
        return out

    mm = (mint or "").strip()
    if not mm:
        return (0, 0.0)
    d = _load_map(db_path)
    return d.get(mm, (0, 0.0))
# --- /BRAIN_HIST_GOOD_BOOST_V1 ---

# --- BRAIN_RLSKIP_FILTER_V1 ---
def _rl_skip_load(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f) or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def _rl_skip_filter_mints(mints, rl_skip: dict, now_ts: int):
    if not rl_skip:
        return mints
    out = []
    for x in (mints or []):
        m = ""
        try:
            if isinstance(x, str):
                m = x.strip()
            elif isinstance(x, dict):
                m = (x.get("mint") or x.get("output_mint") or x.get("address") or "").strip()
        except Exception:
            m = ""
        if not m:
            out.append(x)
            continue
        try:
            until = int(rl_skip.get(m, 0) or 0)
        except Exception:
            until = 0
        if until > now_ts:
            continue
        out.append(x)
    return out
# --- /BRAIN_RLSKIP_FILTER_V1 ---


# --- HIST_FROM_TRADES_V1 ---
import math

def _clamp(x, lo, hi):
    try:
        x = float(x)
    except Exception:
        return lo
    return lo if x < lo else hi if x > hi else x

def _ensure_mint_hist(brain_con):
    brain_con.execute("""
    CREATE TABLE IF NOT EXISTS mint_hist (
        mint TEXT PRIMARY KEY,
        n_closed INTEGER DEFAULT 0,
        n_win INTEGER DEFAULT 0,
        win_rate REAL DEFAULT 0.0,
        avg_pnl REAL DEFAULT 0.0,
        last_close_ts INTEGER DEFAULT 0
    )
    """)
    brain_con.execute("CREATE INDEX IF NOT EXISTS idx_mint_hist_last_close_ts ON mint_hist(last_close_ts)")
    try:
        brain_con.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass

# --- HIST_SCORE_V1 ---
def _mint_hist_score(con, mint: str) -> float:
    """
    Returns a hist score in [0..2].
      - 1.0 = neutral baseline if no history
      - >1.0 boosts mints with good history
      - <1.0 penalizes mints with bad history
    Uses mint_hist(n_closed, win_rate, avg_pnl).
    """
    try:
        mint = str(mint or "").strip()
        if not mint:
            return 1.0
        row = con.execute(
            "SELECT n_closed, win_rate, avg_pnl FROM mint_hist WHERE mint=?",
            (mint,),
        ).fetchone()
        if not row:
            return 1.0

        n_closed = int(row[0] or 0)
        win_rate = float(row[1] or 0.0)
        avg_pnl = float(row[2] or 0.0)

        # confidence grows with samples
        conf = min(1.0, max(0.0, n_closed / 5.0))  # 0..1

        # clamp avg_pnl to avoid insane numbers (your stop_price/max_price fallback can be huge)
        perf = max(-1.0, min(1.0, avg_pnl))  # -1..+1

        # win rate centered at 0.5 -> [-1..+1]
        wr = max(0.0, min(1.0, win_rate))
        win_adj = (wr - 0.5) * 2.0  # -1..+1

        # combine (slightly more weight on win_rate)
        delta = 0.6 * win_adj + 0.4 * perf  # -1..+1
        score = 1.0 + conf * delta
        # --- BRAIN_HIST_GOOD_BOOST_V1 apply ---
        _hist_dbg = (os.getenv("HIST_GOOD_DEBUG","0") == "1")
        # --- BRAIN_HIST_GOOD_MAPFIX_V2 ---
        try:
            if not globals().get('_HIST_GOOD_MAP_CACHED'):
                globals()['_HIST_GOOD_MAP_CACHED'] = True
                globals()['_hist_good_map_cache'] = _hist_good_boost_map(os.getenv('BRAIN_DB_PATH','state/brain.sqlite'))
                _hm = globals().get('_hist_good_map_cache') or {}
                _ks = list(_hm.keys())[:5] if isinstance(_hm, dict) else []
                if _hist_dbg:
                    print(f"🟣 HIST_GOOD map_size={len(_hm) if isinstance(_hm, dict) else -1} sample={_ks}", flush=True)
        except Exception as _e:
            globals()['_hist_good_map_cache'] = {}
            print(f"🟣 HIST_GOOD map_build_error={_e}", flush=True)
        _hist_map = globals().get('_hist_good_map_cache') or {}
        # --- /BRAIN_HIST_GOOD_MAPFIX_V2 ---



        try:
            _m = ""
            # try common local names first
            for _k in ("mint","output_mint","outputMint","address","out_mint"):
                try:
                    _v = locals().get(_k, "")
                    if isinstance(_v, str) and _v.strip():
                        _m = _v.strip()
                        break
                except Exception:
                    pass
            if _m:
                _n, _ap = _hist_good_lookup(_m)
                _min_n = int(float(os.getenv("HIST_GOOD_MIN_N", "2") or 2))
                _t1 = float(os.getenv("HIST_GOOD_AVG_PNL_MIN_1", "0.10") or 0.10)
                _t2 = float(os.getenv("HIST_GOOD_AVG_PNL_MIN_2", "0.25") or 0.25)
                _b1 = float(os.getenv("HIST_GOOD_BOOST_1", "0.15") or 0.15)
                _b2 = float(os.getenv("HIST_GOOD_BOOST_2", "0.30") or 0.30)
                _boost = 0.0
                if _n >= _min_n and _ap >= _t2:
                    _boost = _b2
                elif _n >= _min_n and _ap >= _t1:
                    _boost = _b1
                if _boost:
                    score += _boost


                    if _hist_dbg:
                        print(f"🟢 HIST_GOOD boost mint={_m} n={_n} avg={_ap:.4f} +{_boost} -> score={score:.4f}", flush=True)
        except Exception:
            pass
        # --- /BRAIN_HIST_GOOD_BOOST_V1 apply ---


        # clamp to [0..2]
        if score < 0.0:
            score = 0.0
        elif score > 2.0:
            score = 2.0
        return float(score)
    except Exception:
        return 1.0
# --- /HIST_SCORE_V1 ---
# --- HIST_SCORE_WIRED_V1 ---


def _import_trades_into_brain(brain_con, trades_path="state/trades.sqlite", max_rows=5000):
    import sqlite3, os
    if not trades_path or (not os.path.exists(trades_path)):
        return 0
    _ensure_mint_hist(brain_con)

    tcon = sqlite3.connect(trades_path, timeout=5.0)
    tcur = tcon.cursor()

    # positions table is the best source for closes
    cols = [r[1] for r in tcur.execute("pragma table_info(positions)").fetchall()]
    need = {"mint","entry_price","close_price","close_ts","status"}
    if not need.issubset(set(cols)):
        tcon.close()
        return 0

    rows = tcur.execute("""
        SELECT mint, entry_price, close_price, close_ts
        FROM positions
        WHERE close_ts IS NOT NULL AND CAST(close_ts AS INTEGER) > 0
          AND COALESCE(status,'') != 'open'
        ORDER BY CAST(close_ts AS INTEGER) DESC
        LIMIT ?
    """, (int(max_rows),)).fetchall()
    tcon.close()

    if not rows:
        return 0

    agg = {}  # mint -> [n, nwin, sum_pnl, last_ts]
    for mint, entry, close, cts in rows:
        mint = (mint or "").strip()
        if not mint:
            continue
        try:
            entry = float(entry or 0.0)
            close = float(close or 0.0)
            cts = int(cts or 0)
        except Exception:
            continue
        if entry <= 0 or close <= 0 or cts <= 0:
            continue
        pnl = (close - entry) / entry  # pct as ratio
        n, nwin, sump, last = agg.get(mint, (0,0,0.0,0))
        n += 1
        if pnl > 0:
            nwin += 1
        sump += pnl
        if cts > last:
            last = cts
        agg[mint] = (n, nwin, sump, last)

    for mint, (n, nwin, sump, last) in agg.items():
        win_rate = (nwin / n) if n else 0.0
        avg_pnl = (sump / n) if n else 0.0
        brain_con.execute("""
            INSERT INTO mint_hist(mint,n_closed,n_win,win_rate,avg_pnl,last_close_ts)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(mint) DO UPDATE SET
              n_closed=excluded.n_closed,
              n_win=excluded.n_win,
              win_rate=excluded.win_rate,
              avg_pnl=excluded.avg_pnl,
              last_close_ts=excluded.last_close_ts
        """, (mint, int(n), int(nwin), float(win_rate), float(avg_pnl), int(last)))
    return len(agg)

def _hist_score(brain_con, mint: str) -> float:
    """
    Map history -> [0..2]
    - win_rate matters
    - avg_pnl matters (capped)
    - confidence grows with number of closes
    """
    mint = (mint or "").strip()
    if not mint:
        return 0.0
    try:
        row = brain_con.execute("SELECT n_closed, win_rate, avg_pnl FROM mint_hist WHERE mint=?", (mint,)).fetchone()
    except Exception:
        return 0.0
    if not row:
        return 0.0
    n_closed, win_rate, avg_pnl = row
    try:
        n_closed = int(n_closed or 0)
        win_rate = float(win_rate or 0.0)
        avg_pnl = float(avg_pnl or 0.0)
    except Exception:
        return 0.0

    # confidence: 0..1 (>=5 closes ~ full)
    conf = _clamp(math.sqrt(max(n_closed,0)/5.0), 0.0, 1.0)

    # win part: 0..2
    win_part = _clamp(win_rate * 2.0, 0.0, 2.0)

    # pnl part: normalize avg_pnl (ratio) around [-0.2..+0.2] -> [0..2]
    pnl_part = _clamp((avg_pnl + 0.2) / 0.2, 0.0, 2.0)

    # blend then apply confidence
    base = 0.65 * win_part + 0.35 * pnl_part
    return float(_clamp(base * conf, 0.0, 2.0))
# --- /HIST_FROM_TRADES_V1 ---

# skip_mints split (trader vs brain)
BRAIN_SKIP_MINTS_FILE = os.getenv('BRAIN_SKIP_MINTS_FILE') or os.getenv('SKIP_MINTS_FILE') or 'state/skip_mints_brain.txt'

import urllib.request
import urllib.error
import sqlite3

BRAIN_DB = os.getenv("BRAIN_DB", "state/brain.sqlite")
TRADES_DB = os.getenv("TRADES_DB", "state/trades.sqlite")

READY_IN = os.getenv("BRAIN_READY_IN", "state/ready_to_trade_scored.jsonl")
READY_FALLBACK = os.getenv("BRAIN_READY_FALLBACK", "state/ready_to_trade_enriched.jsonl")

READY_OUT = os.getenv("BRAIN_READY_OUT", "state/ready_scored.jsonl")

TOP_N = int(os.getenv("BRAIN_TOP_N", "120"))
HOLDING_IGNORE_ABOVE = float(os.getenv("HOLDING_IGNORE_ABOVE", "0.05"))  # if holding ui > this => filter out
HOLDING_IGNORE_BELOW = float(os.getenv("HOLDING_IGNORE_BELOW", "0.001"))  # dust ignore
BRAIN_MAX_MC = float(os.getenv("BRAIN_MAX_MC", "50000000"))  # filter majors by market_cap
BRAIN_MAX_LIQ = float(os.getenv("BRAIN_MAX_LIQ", "5000000"))  # filter majors by liquidity
BRAIN_DENY_SYMBOLS = set([x.strip().upper() for x in os.getenv("BRAIN_DENY_SYMBOLS","SOL,USDC,USDT,BONK,JUP,WETH,WBTC,ETH").split(",") if x.strip()])
BRAIN_DENY_SUBSTR = [x.strip().upper() for x in os.getenv("BRAIN_DENY_SUBSTR","USD,EUR,USDC,USDT,EURC").split(",") if x.strip()]
BRAIN_STABLE_PRICE_EPS = float(os.getenv("BRAIN_STABLE_PRICE_EPS","0.03"))  # |price-1| < eps => stable-ish
BRAIN_STABLE_SYMBOLS = set([x.strip().upper() for x in os.getenv("BRAIN_STABLE_SYMBOLS","USDC,USDT,EURC,DAI,USDH,USDS,UXD,USDY").split(",") if x.strip()])
HISTORY_WEIGHT = float(os.getenv("HISTORY_WEIGHT","1.0"))
HISTORY_USD_SCALE = float(os.getenv("HISTORY_USD_SCALE","1.0"))  # 1$ -> 1 unit before tanh
HISTORY_MIN_EVENTS = int(os.getenv("HISTORY_MIN_EVENTS","2"))
HOLDING_IGNORE_ABOVE = float(os.getenv("HOLDING_IGNORE_ABOVE", "0.05"))  # ui amount
MIN_SCORE = float(os.getenv("BRAIN_MIN_SCORE", "0.0"))

# Pondérations (tune plus tard)
W_MARKET = float(os.getenv("BRAIN_W_MARKET", "0.60"))
W_FLOW   = float(os.getenv("BRAIN_W_FLOW",   "0.20"))
W_HIST   = float(os.getenv("BRAIN_W_HIST",   "0.20"))

# “Dust ignore” pour holdings/éviter de bloquer sur des micro restes
DUST_UI = float(os.getenv("HOLDING_DUST_UI", "0.001"))


def _brain_load_skip_mints():
    path = os.getenv("BRAIN_SKIP_MINTS_FILE", "state/skip_mints_brain.txt")
    out = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.add(line)
    except Exception:
        pass
    return out

def _ensure_brain_db():
    if not os.path.exists(BRAIN_DB):
        raise SystemExit(f"brain db missing: {BRAIN_DB}")

def _connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con

def _safe_float(x, d=0.0):
    try:
        if x is None: return d
        return float(x)
    except Exception:
        return d

def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows=[]
    if not os.path.exists(path):
        return rows
    with open(path,"r",encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows

def _pick_ready_input() -> str:
    """
    Pick ready input file.
    Priority:
      1) env READY_FILE if exists and non-empty
      2) state/ready_tradable.jsonl
      3) state/ready_scored.jsonl
      4) state/observed.jsonl
      5) ready_to_trade.jsonl
      6) state/ready_pump_early.jsonl
    """
    import os
    from pathlib import Path

    cands = []

    rf = (os.environ.get("READY_FILE") or "").strip()
    if rf:
        cands.append(rf)

    cands += [
        "state/ready_tradable.jsonl",
        "state/ready_scored.jsonl",
        "state/observed.jsonl",
        "ready_to_trade.jsonl",
        "state/ready_pump_early.jsonl",
    ]

    for fp in cands:
        try:
            if fp and Path(fp).is_file() and Path(fp).stat().st_size > 0:
                return fp
        except Exception:
            pass

    return "state/ready_scored.jsonl"


def _fetch_positions_like(con: sqlite3.Connection) -> Tuple[str, List[str]]:
    cur=con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables={r[0] for r in cur.fetchall()}
    if "positions" in tables:
        cur.execute("PRAGMA table_info(positions)")
        cols=[r[1] for r in cur.fetchall()]
        return "positions", cols
    if "trades" in tables:
        cur.execute("PRAGMA table_info(trades)")
        cols=[r[1] for r in cur.fetchall()]
        return "trades", cols
    return "", []

def _compute_stats_from_trades() -> Dict[str, Dict[str, Any]]:
    """
    Best-effort: s’adapte à ton schema trades.sqlite (positions ou trades).
    On essaie de récupérer: mint, entry_price, exit_price, opened_at, closed_at, close_reason, tp flags.
    """
    stats: Dict[str, Dict[str, Any]] = {}
    if not os.path.exists(TRADES_DB):
        return stats

    con=_connect(TRADES_DB)
    table, cols = _fetch_positions_like(con)
    if not table:
        con.close()
        return stats

    have=set(cols)

    # helper: get column alias if exists
    def col(*names):
        for n in names:
            if n in have: return n
        return None

    c_mint = col("mint","token_mint","token")
    c_entry = col("entry_price","entry")
    c_exit  = col("exit_price","close_price","sold_price","final_price","price_exit")
    c_open  = col("opened_at","open_ts","timestamp","ts_open","created_at")
    c_close = col("closed_at","close_ts","ts_close","updated_at")
    c_reason= col("close_reason","reason")
    c_tp1   = col("tp1_done","tp1")
    c_tp2   = col("tp2_done","tp2")
    c_is_open = col("is_open")

    # Query: récupère tout (open/closed), on calcule surtout sur closed
    sel=[]
    for c in [c_mint,c_entry,c_exit,c_open,c_close,c_reason,c_tp1,c_tp2,c_is_open]:
        if c and c not in sel: sel.append(c)
    q = f"SELECT {', '.join(sel) if sel else '*'} FROM {table}"
    cur=con.cursor()
    try:
        cur.execute(q)
        rows=cur.fetchall()
    except Exception:
        con.close()
        return stats

    # accumulate
    per: Dict[str, List[Dict[str, Any]]] = {}
    now=time.time()
    for r in rows:
        d=dict(r)
        mint = d.get(c_mint) if c_mint else d.get("mint")
        if not mint: 
            continue
        per.setdefault(mint, []).append(d)

    for mint, items in per.items():
        pnls=[]
        holds=[]
        wins=losses=0
        tp1_hits=tp2_hits=0
        sl_hits=time_stops=0
        last_reason=None
        closed_count=0

        for d in items:
            entry=_safe_float(d.get(c_entry), 0.0) if c_entry else 0.0
            exitp=_safe_float(d.get(c_exit), 0.0) if c_exit else 0.0
            opened=_safe_float(d.get(c_open), None) if c_open else None
            closed=_safe_float(d.get(c_close), None) if c_close else None
            reason=(d.get(c_reason) if c_reason else None)

            # closed?
            is_open_val = d.get(c_is_open) if c_is_open else None
            is_closed = False
            if closed is not None and closed > 0:
                is_closed = True
            if is_open_val is not None:
                try:
                    if int(is_open_val)==0:
                        is_closed = True
                except Exception:
                    pass

            if is_closed and entry and exitp:
                pnl=(exitp/entry - 1.0) * 100.0
                pnls.append(pnl)
                closed_count += 1
                if pnl > 0: wins += 1
                else: losses += 1

                if opened and closed and closed > opened:
                    holds.append(closed-opened)

                last_reason = reason

                # reason buckets
                if isinstance(reason,str):
                    rr=reason.lower()
                    if "tp2" in rr: tp2_hits += 1
                    elif "tp1" in rr: tp1_hits += 1
                    elif "hard_sl" in rr or "stop" in rr and "time" not in rr: sl_hits += 1
                    elif "time_stop" in rr: time_stops += 1

            # tp flags if present (even if no exit)
            if c_tp1:
                try:
                    if int(d.get(c_tp1) or 0)==1: tp1_hits = max(tp1_hits, 1)
                except Exception:
                    pass
            if c_tp2:
                try:
                    if int(d.get(c_tp2) or 0)==1: tp2_hits = max(tp2_hits, 1)
                except Exception:
                    pass

        # finalize
        if pnls:
            avg=float(sum(pnls)/len(pnls))
            med=float(statistics.median(pnls))
            worst=float(min(pnls))
            best=float(max(pnls))
        else:
            avg=med=worst=best=None

        if holds:
            avg_h=float(sum(holds)/len(holds))
            med_h=float(statistics.median(holds))
        else:
            avg_h=med_h=None

        stats[mint]={
            "last_update_ts": int(time.time()),
            "trades_total": len(items),
            "trades_closed": closed_count,
            "wins": wins,
            "losses": losses,
            "tp1_hits": tp1_hits,
            "tp2_hits": tp2_hits,
            "sl_hits": sl_hits,
            "time_stops": time_stops,
            "avg_pnl": avg,
            "median_pnl": med,
            "worst_pnl": worst,
            "best_pnl": best,
            "avg_hold_sec": avg_h,
            "median_hold_sec": med_h,
            "last_close_reason": last_reason,
        }

    con.close()
    return stats

def _upsert_mint_stats(brain_con: sqlite3.Connection, stats: Dict[str, Dict[str, Any]]):
    cur=brain_con.cursor()
    for mint, s in stats.items():
        cur.execute("""
        INSERT INTO mint_stats(
          mint,last_update_ts,trades_total,trades_closed,wins,losses,
          tp1_hits,tp2_hits,sl_hits,time_stops,
          avg_pnl,median_pnl,worst_pnl,best_pnl,
          avg_hold_sec,median_hold_sec,last_close_reason
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(mint) DO UPDATE SET
          last_update_ts=excluded.last_update_ts,
          trades_total=excluded.trades_total,
          trades_closed=excluded.trades_closed,
          wins=excluded.wins,
          losses=excluded.losses,
          tp1_hits=excluded.tp1_hits,
          tp2_hits=excluded.tp2_hits,
          sl_hits=excluded.sl_hits,
          time_stops=excluded.time_stops,
          avg_pnl=excluded.avg_pnl,
          median_pnl=excluded.median_pnl,
          worst_pnl=excluded.worst_pnl,
          best_pnl=excluded.best_pnl,
          avg_hold_sec=excluded.avg_hold_sec,
          median_hold_sec=excluded.median_hold_sec,
          last_close_reason=excluded.last_close_reason
        """, (
            mint, s["last_update_ts"], s["trades_total"], s["trades_closed"], s["wins"], s["losses"],
            s["tp1_hits"], s["tp2_hits"], s["sl_hits"], s["time_stops"],
            s["avg_pnl"], s["median_pnl"], s["worst_pnl"], s["best_pnl"],
            s["avg_hold_sec"], s["median_hold_sec"], s["last_close_reason"]
        ))
    brain_con.commit()

def _get_history(brain_con: sqlite3.Connection, mint: str) -> Optional[sqlite3.Row]:
    cur=brain_con.cursor()
    cur.execute("SELECT * FROM mint_stats WHERE mint=?", (mint,))
    return cur.fetchone()

def _score_market(o: Dict[str, Any]) -> float:
    # score basé sur données DexScreener enrichies
    liq=_safe_float(o.get("liquidity_usd"), 0.0)
    vol1h=_safe_float(o.get("vol_1h"), 0.0)
    tx5=_safe_float(o.get("txns_5m"), 0.0)
    chg5=_safe_float(o.get("chg_5m"), 0.0)
    chg1=_safe_float(o.get("chg_1h"), 0.0)

    # normalisations “soft” (log-like sans log)
    s=0.0
    s += min(1.0, liq/250000.0) * 25.0
    s += min(1.0, vol1h/200000.0) * 30.0
    s += min(1.0, tx5/80.0) * 25.0

    # momentum : si chg5 ou chg1 positif, bonus; si violent négatif, malus léger
    s += max(-10.0, min(10.0, chg5)) * 0.6
    s += max(-10.0, min(10.0, chg1)) * 0.4
    return s

def _score_history(h: Optional[sqlite3.Row]) -> float:
    if h is None:
        return 0.0
    wins = int(h["wins"] or 0)
    losses = int(h["losses"] or 0)
    closed = int(h["trades_closed"] or 0)
    avg_pnl = h["avg_pnl"]
    worst = h["worst_pnl"]

    # winrate
    wr = (wins / max(1, wins+losses))
    s = (wr - 0.5) * 40.0  # [-20..+20] approx

    # avg pnl
    if avg_pnl is not None:
        s += max(-20.0, min(20.0, float(avg_pnl))) * 0.7

    # worst drawdown penalty
    if worst is not None:
        s += max(-30.0, float(worst)) * 0.3

    # si on a déjà fermé plusieurs fois ce mint => confiance (ou méfiance)
    if closed >= 3:
        s += 5.0
    return s

def _score_flow(o: Dict[str, Any]) -> float:
    # score “qualité route/dex” simple (tu auras ton strict gate côté Jupiter)
    dex = (o.get("dex_id") or "").lower()
    if dex in ("orca","raydium","meteora"):
        return 8.0
    if dex in ("pumpswap","pumpfun"):
        return 4.0
    return 2.0



def _brain_rpc(url: str, method: str, params: list, timeout: int = 12):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    out = json.loads(raw)
    if isinstance(out, dict) and out.get("error"):
        raise RuntimeError(out["error"])
    return out.get("result")

def _brain_wallet_holdings_set(pubkey: str, thr: float, dust: float) -> set:
    """
    Returns set(mint) where wallet uiAmount > thr (dust ignored below dust).
    Uses getTokenAccountsByOwner jsonParsed.
    """
    if not pubkey or thr <= 0:
        return set()

    rpc = os.getenv("SOLANA_RPC_HTTP") or os.getenv("RPC_HTTP") or "https://api.mainnet-beta.solana.com"
    try:
        res = _brain_rpc(
            rpc,
            "getTokenAccountsByOwner",
            [pubkey, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding": "jsonParsed"}],
            timeout=12
        )
    except Exception as e:
        print("🧠 brain_loop: holdings rpc failed:", e)
        return set()

    hits = set()
    try:
        vals = (res or {}).get("value") or []
        for it in vals:
            info = (((it or {}).get("account") or {}).get("data") or {}).get("parsed") or {}
            if info.get("type") != "account":
                continue
            mint = ((info.get("info") or {}).get("mint") or "").strip()
            tok = (info.get("info") or {}).get("tokenAmount") or {}
            ui = tok.get("uiAmount")
            if ui is None:
                try:
                    ui = float(tok.get("uiAmountString") or 0.0)
                except Exception:
                    ui = 0.0
            try:
                ui = float(ui or 0.0)
            except Exception:
                ui = 0.0

            if ui <= float(dust):
                continue
            if ui > float(thr):
                hits.add(mint)
    except Exception as e:
        print("🧠 brain_loop: holdings parse failed:", e)
        return set()

    return hits




def _brain_history_score(db_path: str, mint: str) -> tuple:
    """
    Returns (history_score, usd_net, n_events).
    score in [-20,+20] roughly.
    """
    if not db_path or not mint:
        return (0.0, 0.0, 0)

    try:
        con = sqlite3.connect(db_path, timeout=2.0)
        # --- HIST_RUNONCE_HOOK_V1 ---
        try:
            _ensure_mint_hist(con)
        except Exception as _e:
            print("hist ensure failed:", _e)
        # --- /HIST_RUNONCE_HOOK_V1 ---

        row = con.execute(
            "select usd_net, n_events from token_stats where token_address=?",
            (mint,)
        ).fetchone()
        con.close()
        if not row:
            return (0.0, 0.0, 0)
        usd_net = float(row[0] or 0.0)
        n_events = int(row[1] or 0)
    except Exception:
        return (0.0, 0.0, 0)

    # confidence: more events => stronger
    if n_events < int(HISTORY_MIN_EVENTS):
        return (0.0, usd_net, n_events)

    # squash: tanh-like without importing math.tanh heavy logic
    # approx: x/(1+abs(x)) -> [-1,1]
    x = (usd_net / max(1e-9, float(HISTORY_USD_SCALE)))
    x = x / (1.0 + abs(x))
    score = 20.0 * float(HISTORY_WEIGHT) * x
    return (float(score), float(usd_net), int(n_events))





def _brain_is_stable_like(o: dict) -> bool:
    """
    Heuristics to filter stablecoins / pegged assets / majors.
    - symbol in BRAIN_STABLE_SYMBOLS -> True
    - symbol contains substrings in BRAIN_DENY_SUBSTR (USD/EUR/USDC/USDT/EURC) -> True
    - price close to 1.0 (+/- eps) AND (symbol looks like USD/EUR) -> True
    """
    try:
        sym = str(o.get("symbol","") or "").upper().strip()
        if sym:
            if sym in BRAIN_STABLE_SYMBOLS:
                return True
            subs = [x.strip().upper() for x in str(BRAIN_DENY_SUBSTR or "").split(",") if x.strip()]
            for sub in subs:
                if sub and sub in sym:
                    return True

        # price-based peg detection (only if symbol hints USD/EUR)
        px = float(o.get("price_usd") or 0.0)
        if px > 0:
            eps = float(BRAIN_STABLE_PRICE_EPS or 0.03)
            if abs(px - 1.0) <= eps:
                if ("USD" in sym) or ("USDT" in sym) or ("USDC" in sym) or ("EUR" in sym) or ("DAI" in sym):
                    return True
    except Exception:
        return False
    return False
def run_once(note: str = "brain_loop"):
    # --- HIST_FROM_TRADES_V1 (run_once hook) ---
    try:
        _brain_path = str(locals().get('db_path') or os.getenv('BRAIN_DB_PATH','state/brain.sqlite')).strip()
        _trades_path = str(os.getenv('TRADES_DB_PATH','state/trades.sqlite')).strip()
        _max_rows = int(os.getenv('HIST_MAX_ROWS','8000'))
        _hist_every_s = float(os.getenv('HIST_IMPORT_EVERY_S','15') or 15.0)
        _now = time.time()
        _last = float(getattr(run_once, '_last_hist_import_ts', 0.0) or 0.0)

        if _now - _last >= _hist_every_s:
            setattr(run_once, '_last_hist_import_ts', _now)

            if os.path.exists(_trades_path):
                tcon = sqlite3.connect(_trades_path, timeout=5.0)
                tcur = tcon.cursor()

                try:
                    pos_rows = tcur.execute(
                        """
                        select mint, entry_price, close_price, max_price,
                               stop_price, close_ts, close_reason, status
                        from positions
                        where (close_ts is not null
                               or upper(coalesce(status,''))='CLOSED')
                        order by coalesce(close_ts,0) desc
                        limit ?
                        """,
                        (_max_rows,)
                    ).fetchall()
                except Exception:
                    pos_rows = []

                agg = dict()

                for row in pos_rows:
                    mint, entry, closep, maxp, stopp, cts, reason, status = row
                    if not mint or not cts:
                        continue

                    entry = float(entry or 0.0)
                    closep = float(closep or 0.0)
                    rs = str(reason or '').lower()

                    pnl = None

                    if entry > 0 and closep > 0:
                        pnl = (closep/entry) - 1.0

                    if pnl is None:
                        if 'hard_sl' in rs:
                            pnl = -0.35
                        elif 'trailing' in rs:
                            pnl = 0.10
                        elif 'time_stop' in rs:
                            pnl = -0.05
                        elif 'dust' in rs:
                            pnl = -0.02
                        elif 'resync' in rs:
                            pnl = -0.02
                        else:
                            pnl = 0.0

                    pnl = max(-0.9, min(2.0, pnl))

                    n_closed, n_win, sum_score, last_ts = agg.get(mint, (0,0,0.0,0))
                    n_closed += 1
                    if pnl > 0:
                        n_win += 1
                    sum_score += pnl
                    last_ts = max(int(cts), int(last_ts))

                    agg[mint] = (n_closed, n_win, sum_score, last_ts)

                tcon.close()

                bcon = sqlite3.connect(_brain_path, timeout=2.0)
                try:
                    _ensure_mint_hist(bcon)
                except Exception:
                    pass

                up = 0
                for mint,(n_closed,n_win,sum_score,last_ts) in agg.items():
                    win_rate = (float(n_win)/float(n_closed)) if n_closed>0 else 0.0
                    avg_pnl = (float(sum_score)/float(n_closed)) if n_closed>0 else 0.0

                    bcon.execute(
                        """
                        INSERT OR REPLACE INTO mint_hist
                        (mint,n_closed,n_win,win_rate,avg_pnl,last_close_ts)
                        VALUES(?,?,?,?,?,?)
                        """,
                        (mint,int(n_closed),int(n_win),
                         float(win_rate),float(avg_pnl),int(last_ts))
                    )
                    up += 1

                bcon.commit()
                bcon.close()

                print("hist_import: pos_rows=%d used=%d mints=%d upsert=%d brain=%s trades=%s" % (
                    len(pos_rows), len(agg), len(agg), up, _brain_path, _trades_path
                ), flush=True)

    except Exception as _e:
        print("hist_import failed:", _e, flush=True)
    # --- /HIST_FROM_TRADES_V1 (run_once hook) ---

    _ensure_brain_db()
    brain=_connect(BRAIN_DB)

    # mark run
    # --- brain_runs schema compat ---
    try:
        import os as _os
        _cols = [r[1] for r in brain.execute("PRAGMA table_info(brain_runs)").fetchall()]
        _now = int(time.time())
        if ("ts" in _cols) and ("note" in _cols):
            brain.execute("INSERT INTO brain_runs(ts,note) VALUES (?,?)", (_now, note))
        elif ("ts_start" in _cols) and ("notes" in _cols):
            _mode = _os.environ.get("BRAIN_MODE", "loop")
            brain.execute("INSERT INTO brain_runs(ts_start,mode,notes) VALUES (?,?,?)", (_now, _mode, note))
        elif ("notes" in _cols):
            brain.execute("INSERT INTO brain_runs(notes) VALUES (?)", (note,))
        else:
            pass
    except Exception:
        pass
    # --- end schema compat ---
    brain.commit()
    # update stats from trades
    stats=_compute_stats_from_trades()
    if stats:
        _upsert_mint_stats(brain, stats)

    # load ready candidates
    ready_path=_pick_ready_input()
    ready=_load_jsonl(ready_path)

    scored=[]
    now=int(time.time())
    for o in ready:
        mint=o.get("mint")
        if not mint: 
            continue

        mkt=_score_market(o)
        flow=_score_flow(o)
        hist = _mint_hist_score(brain, mint)  # HIST_WIRE_MINT_HIST_V1

        # --- HIST_METRICS_V1 ---
        hist_n = 0
        hist_wr = 0.0
        hist_avg = 0.0
        try:
            _r = brain.execute("SELECT n_closed, win_rate, avg_pnl FROM mint_hist WHERE mint=?", (mint,)).fetchone()
            if _r:
                hist_n = int(_r[0] or 0)
                hist_wr = float(_r[1] or 0.0)
                hist_avg = float(_r[2] or 0.0)
        except Exception:
            pass
        # penalize bad history (simple, safe)
        try:
            _min_n = int(os.getenv('HIST_BLOCK_MIN_N','2'))
            _bad_avg = float(os.getenv('HIST_BLOCK_AVG_PNL','-0.10'))
            _pen = float(os.getenv('HIST_BAD_PENALTY','0.25'))
            if hist_n >= _min_n and hist_avg <= _bad_avg:
                hist = max(0.0, hist - _pen)
        except Exception:
            pass
        # --- /HIST_METRICS_V1 ---

        score = W_MARKET*mkt + W_FLOW*flow + W_HIST*hist

        hist = _hist_score(brain, mint)
        reason=f"mkt={mkt:.2f} flow={flow:.2f} hist={hist:.2f} hn={hist_n} hwr={hist_wr:.2f} havg={hist_avg:.2f} w=({W_MARKET},{W_FLOW},{W_HIST})"

        # upsert score
        brain.execute("""
        INSERT INTO mint_scores(mint,scored_at_ts,score,score_market,score_flow,score_history,reason)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(mint) DO UPDATE SET
          scored_at_ts=excluded.scored_at_ts,
          score=excluded.score,
          score_market=excluded.score_market,
          score_flow=excluded.score_flow,
          score_history=excluded.score_history,
          reason=excluded.reason
        """, (mint, now, float(score), float(mkt), float(flow), float(hist), reason))

        o2=dict(o)
        o2["brain_score"]=round(float(score), 4)
        o2["brain_score_market"]=round(float(mkt), 4)
        o2["brain_score_flow"]=round(float(flow), 4)
        o2["brain_score_history"]=round(float(hist), 4)
        o2["brain_scored_at"]=now
        scored.append(o2)

    brain.commit()
    brain.close()

    scored.sort(key=lambda x: float(x.get("brain_score") or 0.0), reverse=True)

    # apply min score + topN
    out=[]
    for x in scored:
        if float(x.get("brain_score") or 0.0) < MIN_SCORE:
            continue
        out.append(x)
        if len(out) >= TOP_N:
            break

    # --- brain: filter holdings + majors (BEFORE writing file) ---
    try:
        pub = os.getenv("WALLET_PUBKEY","") or os.getenv("TRADER_USER_PUBLIC_KEY","")
        thr = float(HOLDING_IGNORE_ABOVE)
        dust = float(HOLDING_IGNORE_BELOW)
        hold_mints = _brain_wallet_holdings_set(pub, thr, dust)
        if hold_mints:
            _b = len(out)
            out = [o for o in out if str(o.get("mint","")) not in hold_mints]
            if len(out) != _b:
                print(f"🧠 brain_loop: filtered_by_holding_rpc={_b-len(out)} remaining={len(out)} thr={thr} dust={dust}")
    except Exception as _e:
        print("🧠 brain_loop: holdings filter failed:", _e)

    try:
        _b = len(out)
        tmp=[]
        for o in out:
            sym = str(o.get("symbol","") or "").upper().strip()
            if sym and sym in BRAIN_DENY_SYMBOLS:
                continue
            mc = float(o.get("market_cap") or 0.0)
            liq = float(o.get("liquidity_usd") or 0.0)
            if (BRAIN_MAX_MC > 0 and mc > BRAIN_MAX_MC):
                continue
            if (BRAIN_MAX_LIQ > 0 and liq > BRAIN_MAX_LIQ):
                continue
            tmp.append(o)
        out = tmp
        if len(out) != _b:
            print(f"🧠 brain_loop: filtered_majors={_b-len(out)} remaining={len(out)} max_mc={BRAIN_MAX_MC} max_liq={BRAIN_MAX_LIQ}")
    except Exception as _e:
        print("🧠 brain_loop: majors filter failed:", _e)

    # --- filter stables / pegged / symbols (EURC etc) ---
    try:
        _before = len(out)
        out = [o for o in out if not _brain_is_stable_like(o)]
        if len(out) != _before:
            print(f"🧠 brain_loop: filtered_stables={_before-len(out)} remaining={len(out)}")
    except Exception as _e:
        print("🧠 brain_loop: stable filter failed:", _e)
    with open(READY_OUT,"w",encoding="utf-8") as w:
        for x in out:
            w.write(json.dumps(x, ensure_ascii=False) + "\n")

    # --- brain: filter out skip_mints (already holding / manual skip) ---
    skip_mints = set()
    try:
        skip_mints = _brain_load_skip_mints() or set()
    except Exception:
        skip_mints = set()
    if skip_mints:
        _before = len(out)
        out = [o for o in out if str(o.get('mint','')) not in skip_mints]
        _removed = _before - len(out)
        if _removed > 0:
            print(f"🧠 brain_loop: filtered_by_skip={_removed} remaining={len(out)}")

    os.makedirs(os.path.dirname(READY_OUT) or '.', exist_ok=True)
    with open(READY_OUT, 'w', encoding='utf-8') as w:
        for x in out:
            w.write(json.dumps(x, ensure_ascii=False) + '\n')

    print(f"🧠 brain_loop: ready_in={ready_path} in={len(ready)} -> out={len(out)} file={READY_OUT}")

    # --- BRAIN_RLSKIP_APPLY_V1 ---
    try:
        _rl_file = str(os.getenv("RL_SKIP_FILE", "state/rl_skip_mints.json") or "state/rl_skip_mints.json")
        _now = int(time.time())
        _d = _rl_skip_load(_rl_file)
        _before = len(ready) if isinstance(ready, list) else -1
        if isinstance(ready, list) and _before > 0 and _d:
            ready = _rl_skip_filter_mints(ready, _d, _now)
            _after = len(ready)
            if _after != _before:
                print(f"🧊 RL_SKIP filtered ready (brain): {_before}->{_after} file={_rl_file}", flush=True)
    except Exception as _e:
        print("rl_skip_filter_error(brain):", _e, flush=True)
    # --- /BRAIN_RLSKIP_APPLY_V1 ---
    if out:
        print("🧠 top1:", out[0].get('mint'), "score=", out[0].get('brain_score'))

if __name__ == "__main__":
    run_once()
