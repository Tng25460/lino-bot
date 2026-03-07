#!/usr/bin/env bash
set -euo pipefail
cd /home/tng25/lino_FINAL_20260203_182626 || exit 1
source .venv/bin/activate || true

WALLET="${WALLET_PUBKEY:-9U69xxU9eWRebdQ99FSo2FBwfafQZYjL4DT6ZFLqwmga}"

# 1) merge ready*.jsonl -> state/ready_wide.noheld.jsonl (exclut holdings onchain via spl-token)
python - <<'PY'
import json, glob, subprocess, os
from pathlib import Path

WALLET=os.getenv("WALLET_PUBKEY","")
held=set()
try:
    out=subprocess.check_output(
        ["spl-token","accounts","--owner",WALLET,"--url","https://api.mainnet-beta.solana.com"],
        text=True, stderr=subprocess.STDOUT
    )
    for ln in out.splitlines()[2:]:
        parts=ln.split()
        if len(parts)>=2:
            mint=parts[0].strip()
            try:
                bal=float(parts[1].strip())
            except:
                bal=0.0
            if bal>0:
                held.add(mint)
except Exception:
    pass

files=sorted(set(glob.glob("state/ready*.jsonl")))
files=[f for f in files if Path(f).is_file() and Path(f).stat().st_size>0]

best={}
def score_of(o):
    for k in ("brain_score","score"):
        if k in o:
            try: return float(o.get(k) or 0.0)
            except: pass
    return 0.0

for f in files:
    for ln in Path(f).read_text(encoding="utf-8", errors="ignore").splitlines():
        ln=ln.strip()
        if not ln or not ln.startswith("{"): continue
        try:
            o=json.loads(ln)
        except:
            continue
        m=o.get("mint")
        if not m or m in held: 
            continue
        sc=score_of(o)
        prev=best.get(m)
        if (prev is None) or (sc > score_of(prev)):
            best[m]=o

rows=list(best.values())
rows.sort(key=score_of, reverse=True)

outp=Path("state/ready_wide.noheld.jsonl")
outp.write_text("\n".join(json.dumps(o, separators=(",",":"), ensure_ascii=False) for o in rows) + ("\n" if rows else ""), encoding="utf-8")
print("OUT", outp, "lines=", len(rows), "files=", len(files), "held=", len(held))
PY

# 2) filter tradable via Jupiter quote
python -u scripts/filter_ready_tradable.py \
  --in  state/ready_wide.noheld.jsonl \
  --out state/ready_wide.noheld.tradable.jsonl \
  --jup https://lite-api.jup.ag \
  --amount 3000000 \
  --slip-bps 450 \
  --retries 2 \
  --min-interval-sec 0.35 \
  --on429-keep 1 \
  --top-n 250 \
  >/dev/null

# 3) canonical copy (REAL FILE, pas symlink)
cp -f state/ready_wide.noheld.tradable.jsonl state/ready_scored_tradable.jsonl

echo "[OK] canonical ready_scored_tradable.jsonl lines=$(wc -l < state/ready_scored_tradable.jsonl)"
