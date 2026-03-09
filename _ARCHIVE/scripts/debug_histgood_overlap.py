#!/usr/bin/env python3
import json, sqlite3
from pathlib import Path

ready_path = Path("state/ready_tradable.jsonl")
db_path = Path("state/brain.sqlite")

con = sqlite3.connect(str(db_path))
cur = con.cursor()

# load mint_hist -> dict
hist = {}
for mint, n_closed, avg_pnl, last_ts in cur.execute("""
    SELECT mint, n_closed, avg_pnl, last_close_ts
    FROM mint_hist
"""):
    hist[str(mint)] = (int(n_closed or 0), float(avg_pnl or 0.0), int(last_ts or 0))

ready = []
for ln in ready_path.read_text(encoding="utf-8", errors="ignore").splitlines():
    ln = ln.strip()
    if not ln: 
        continue
    try:
        o = json.loads(ln)
    except Exception:
        continue
    m = (o.get("mint") or o.get("output_mint") or o.get("outputMint") or o.get("address") or "").strip()
    if m:
        ready.append(m)

ready_set = set(ready)
overlap = sorted(list(ready_set & set(hist.keys())))

print("mint_hist_size:", len(hist))
print("ready_size:", len(ready_set))
print("overlap_size:", len(overlap))

# show overlap sample with stats
print("\noverlap_sample (mint, n_closed, avg_pnl, last_close_ts):")
for m in overlap[:20]:
    n, ap, ts = hist[m]
    print(m, n, round(ap, 4), ts)

# show "good" according to thresholds (defaults same as your env idea)
HIST_GOOD_MIN_N = 1
AVG1 = 0.05
AVG2 = 0.20

good = []
for m in overlap:
    n, ap, ts = hist[m]
    if n >= HIST_GOOD_MIN_N and ap >= AVG1:
        good.append((m, n, ap, ts))

good.sort(key=lambda x: (x[2], x[1], x[3]), reverse=True)
print(f"\ngood_overlap (n>={HIST_GOOD_MIN_N} and avg>={AVG1}) size:", len(good))
for r in good[:20]:
    print(r[0], r[1], round(r[2], 4), r[3])

