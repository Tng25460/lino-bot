#!/usr/bin/env python3
import json, sqlite3, time
from pathlib import Path

# --- REENTRY_LOCK_V1 ---
import os, time

TRADES_DB = os.getenv("TRADES_DB_PATH", "state/trades.sqlite")
SKIP_FILE = os.getenv("SKIP_MINTS_FILE", "state/skip_mints_trader.txt")
RL_SKIP_FILE = os.getenv("RL_SKIP_FILE", "state/rl_skip_mints.json")

def _load_skip_file(path: str) -> set[str]:
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return set()
    out=set()
    for ln in txt.splitlines():
        ln=ln.strip()
        if not ln or ln.startswith("#"): 
            continue
        out.add(ln.split()[0])
    return out

def _load_rlskip(path: str) -> dict:
    try:
        import json
        p=Path(path)
        if not p.exists(): return {}
        d=json.loads(p.read_text(encoding="utf-8", errors="ignore") or "{}")
        # tolerate legacy int format
        out={}
        now=int(time.time())
        for mint,v in (d or {}).items():
            if isinstance(v,int):
                out[mint]={"until": v, "reason":"legacy_int", "ts": now}
            elif isinstance(v,dict):
                until=v.get("until",0)
                try: until=int(until)
                except Exception: until=0
                out[mint]={"until": until, "reason": v.get("reason",""), "ts": int(v.get("ts", now) or now)}
        return out
    except Exception:
        return {}

def _is_rlskip_active(rl: dict, mint: str, now: int) -> bool:
    v=rl.get(mint)
    if not isinstance(v,dict): 
        return False
    try:
        return int(v.get("until",0)) > now
    except Exception:
        return False

def _open_position_mints(trades_db: str) -> set[str]:
    import sqlite3
    p=Path(trades_db)
    if not p.exists():
        return set()
    con=sqlite3.connect(str(p))
    cur=con.cursor()
    # find a positions-like table
    tables=[r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    cand=[t for t in tables if t.lower() in ("positions","open_positions","position")]
    if not cand:
        # fallback: any table containing 'position'
        cand=[t for t in tables if "position" in t.lower()]
    if not cand:
        return set()
    t=cand[0]
    cols=[r[1] for r in cur.execute(f"PRAGMA table_info({t})").fetchall()]
    # mint column
    mint_col=None
    for c in ["mint","output_mint","outputMint","token_mint"]:
        if c in cols:
            mint_col=c; break
    if not mint_col:
        return set()
    # open predicate
    where=None
    if "is_open" in cols:
        where="is_open=1"
    elif "close_ts" in cols:
        where="close_ts IS NULL OR close_ts=0"
    elif "closed_ts" in cols:
        where="closed_ts IS NULL OR closed_ts=0"
    elif "close_time" in cols:
        where="close_time IS NULL OR close_time=0"
    else:
        # no known close flag => don't risk false positives
        return set()
    q=f"SELECT DISTINCT {mint_col} FROM {t} WHERE {where}"
    out=set()
    try:
        for (m,) in cur.execute(q).fetchall():
            if m: out.add(str(m))
    finally:
        con.close()
    return out
# --- /REENTRY_LOCK_V1 ---

READY_IN = Path("state/ready_tradable.jsonl")
READY_OUT = Path("state/ready_tradable_plus_histgood.jsonl")
DB = "state/brain.sqlite"
MAX_ADD = 8
REENTRY_RL_SKIP_SEC = 6*3600
REENTRY_IGNORE_SKIP_FILE = (os.getenv("REENTRY_IGNORE_SKIP_FILE","0")=="1")
RL_SKIP_PATH = Path('state/rl_skip_mints.json')


def _rlskip_add(mint: str, sec: int, reason: str = "reentry_histgood"):
    try:
        now = int(time.time())
        path = RL_SKIP_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8", errors="ignore") or "{}")
            except Exception:
                data = {}
        data[mint] = {"until": now + int(sec), "reason": reason, "ts": now}
        path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


# load existing ready mints
ready_lines = READY_IN.read_text(encoding="utf-8", errors="ignore").splitlines()
ready_mints = set()
for ln in ready_lines:
    ln = ln.strip()
    if not ln:
        continue
    try:
        o = json.loads(ln)
    except Exception:
        continue
    m = (o.get("mint") or o.get("output_mint") or o.get("outputMint") or o.get("address") or "").strip()
    if m:
        ready_mints.add(m)

# --- REENTRY_LOCK_APPLIED_V1 ---
_now = int(time.time())
_skip = _load_skip_file(SKIP_FILE)
_rl = _load_rlskip(RL_SKIP_FILE)
_open = _open_position_mints(TRADES_DB)
# --- /REENTRY_LOCK_APPLIED_V1 ---

# --- REENTRY_DEBUG_V1 ---
_dbg = (os.getenv("REENTRY_DEBUG","0") == "1")
_cnt_total = 0
_cnt_block_skip = 0
_cnt_block_open = 0
_cnt_block_rl = 0
_cnt_added = 0
# --- /REENTRY_DEBUG_V1 ---

con = sqlite3.connect(DB)
cur = con.cursor()

# pick "good" from mint_hist (n_closed>=1 & avg_pnl>=0.05)
good = [r[0] for r in cur.execute("""
SELECT mint, n_closed, avg_pnl, last_close_ts
FROM mint_hist
WHERE n_closed>=1 AND avg_pnl>=0.05
ORDER BY avg_pnl DESC, last_close_ts DESC
LIMIT ?
""", (MAX_ADD,)).fetchall()]

added = 0
out_lines = list(ready_lines)
for m in good:
    if m not in ready_mints:
        out_lines.append(json.dumps({"mint": m, "tag": "hist_good_reentry"}, separators=(",",":")))
        ready_mints.add(m)
# guard reentry candidates (skip/open/rlskip)
        if (m in _skip) or (m in _open) or _is_rlskip_active(_rl, m, _now):
            # blocked -> do not add / do not refresh
            continue
        _rlskip_add(m, REENTRY_RL_SKIP_SEC, "reentry_histgood")
        _cnt_added += 1
        added += 1
READY_OUT.write_text("\n".join([ln for ln in out_lines if ln.strip()]) + "\n", encoding="utf-8")
# --- REENTRY_DEBUG_PRINT_FIX_V3 ---
if os.getenv('REENTRY_DEBUG','0') == '1':
    try:
        print(f"[REENTRY_DEBUG] total={_cnt_total} block_skip={_cnt_block_skip} block_open={_cnt_block_open} block_rlskip={_cnt_block_rl} added={_cnt_added}")
        _blocks = globals().get('_dbg_blocks', None)
        if isinstance(_blocks, list):
            for mm,bs,bo,br in _blocks[:40]:
                print(f"[REENTRY_DEBUG] block mint={mm} skip={bs} open={bo} rlskip={br}")
    except Exception as e:
        print(f"[REENTRY_DEBUG] print_error={e}")
# --- /REENTRY_DEBUG_PRINT_FIX_V3 ---
print(f"[OK] wrote {READY_OUT} lines={len(out_lines)} added_histgood={added}")
