import sqlite3, json
from pathlib import Path

DB="state/trades.sqlite"
if not Path(DB).exists():
    print("NO trades.sqlite")
    raise SystemExit(1)

con=sqlite3.connect(DB)
cur=con.cursor()

cols=[r[1] for r in cur.execute("PRAGMA table_info(positions)").fetchall()]
need=set(["mint","status"])
if not need.issubset(set(cols)):
    print("ERROR: positions table missing required columns:", sorted(need-set(cols)))
    raise SystemExit(2)

# choose price columns
entry_col = "entry_price" if "entry_price" in cols else ("entry_price_usd" if "entry_price_usd" in cols else None)
close_col = "close_price" if "close_price" in cols else ("close_price_usd" if "close_price_usd" in cols else None)

if not entry_col or not close_col:
    print("ERROR: cannot find entry/close price columns. have:", cols)
    raise SystemExit(3)

q=f"""
SELECT mint, {entry_col} as entry_p, {close_col} as close_p
FROM positions
WHERE lower(coalesce(status,'')) IN ('closed','close','closed ')
"""
rows=cur.execute(q).fetchall()

def profile_of(mint: str) -> str:
    m=(mint or "").lower()
    return "PUMP" if m.endswith("pump") or m.find("pump")!=-1 else "NORMAL"

stats={}
for mint, entry_p, close_p in rows:
    try:
        entry=float(entry_p or 0.0)
        close=float(close_p or 0.0)
    except Exception:
        continue
    # ignore invalid prices
    if entry <= 0 or close <= 0:
        continue
    pnl_pct=(close-entry)/entry
    prof=profile_of(mint)

    s=stats.setdefault(prof, {"trades":0,"wins":0,"sum_pnl":0.0})
    s["trades"] += 1
    s["wins"] += 1 if pnl_pct > 0 else 0
    s["sum_pnl"] += pnl_pct

# finalize
out={}
for prof, s in stats.items():
    n=s["trades"]
    if n<=0: 
        continue
    out[prof]={
        "trades": n,
        "winrate_pct": round(100.0*s["wins"]/n, 2),
        "avg_pnl_pct": round(100.0*s["sum_pnl"]/n, 4),  # in %
    }

Path("state/brain_v3_stats.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print("OK brain stats:", out)
