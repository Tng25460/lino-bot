#!/usr/bin/env python3
import os, json, time, sqlite3
from pathlib import Path

RL = Path(os.getenv("RL_SKIP_FILE","state/rl_skip_mints.json"))
BRAIN = Path(os.getenv("BRAIN_DB_PATH","state/brain.sqlite"))

min_n = int(float(os.getenv("HIST_SKIP_MIN_N","1") or 1))
max_avg = float(os.getenv("HIST_SKIP_AVG_PNL_MAX","-0.10") or -0.10)
sec = int(float(os.getenv("HIST_SKIP_SEC","3600") or 3600))
limit = int(float(os.getenv("HIST_SKIP_LIMIT","250") or 250))
max_age = int(float(os.getenv("HIST_SKIP_MAX_AGE_S","0") or 0))

now = int(time.time())
cut_ts = now - max_age if max_age > 0 else 0

if not BRAIN.exists():
    raise SystemExit(f"[ERR] brain db not found: {BRAIN}")

con = sqlite3.connect(str(BRAIN))
cur = con.cursor()

q = """
SELECT mint, n_closed, avg_pnl, last_close_ts
FROM mint_hist
WHERE n_closed >= ?
  AND avg_pnl <= ?
"""
params = [min_n, max_avg]
if cut_ts > 0:
    q += " AND last_close_ts >= ?"
    params.append(cut_ts)
q += " ORDER BY last_close_ts DESC LIMIT ?"
params.append(limit)

rows = cur.execute(q, params).fetchall()
con.close()

# load current rl_skip
try:
    d = json.loads(RL.read_text(encoding="utf-8")) if RL.exists() else {}
    if not isinstance(d, dict):
        d = {}
except Exception:
    d = {}

# clean existing: no empty keys, no expired
clean = {}
for k, v in (d or {}).items():
    k = str(k).strip()
    if not k:
        continue
    try:
        until = int(v)
    except Exception:
        continue
    if until > now:
        clean[k] = until

# upsert bad mints -> now+sec
upserted = 0
for mint, n_closed, avg_pnl, last_close_ts in rows:
    m = str(mint or "").strip()
    if not m:
        continue
    until = now + sec
    prev = int(clean.get(m, 0) or 0)
    if prev < until:
        clean[m] = until
        upserted += 1

RL.parent.mkdir(parents=True, exist_ok=True)
RL.write_text(json.dumps(clean, separators=(",",":")), encoding="utf-8")

print(f"[OK] rlskip_sync brain={BRAIN} file={RL} now={now} min_n={min_n} max_avg={max_avg} sec={sec} max_age={max_age}")
print(f"[OK] mint_hist_bad_rows={len(rows)} upserted={upserted} active_total={len(clean)}")
