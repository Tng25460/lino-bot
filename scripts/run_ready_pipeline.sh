#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p state

# thresholds (can be overridden from env before calling)
export MIN_LIQ_USD="${MIN_LIQ_USD:-3000}"
export MIN_TX_5M="${MIN_TX_5M:-5}"
export MIN_VOL_5M_USD="${MIN_VOL_5M_USD:-300}"

# 1) produce tradable scored list
bash scripts/filter_tradable.sh

# 2) build canonical READY file
bash scripts/build_ready_canonical.sh

# 3) final deny: tokenized equities/actions (symbol like AAPLx etc.)
python - <<'PY'
import json,re
from pathlib import Path
rx=re.compile(r"^[A-Z]{1,6}x$")
inp=Path("state/READY_CANONICAL.jsonl")
tmp=Path("state/READY_CANONICAL.jsonl.tmp")
kept=dropped=0
with inp.open() as f, tmp.open("w") as g:
    for line in f:
        line=line.strip()
        if not line: continue
        try: o=json.loads(line)
        except: continue
        sym=(o.get("symbol") or "").strip()
        name=(o.get("name") or "").strip().lower()
        if rx.match(sym) or any(k in name for k in ["stock","equity","etf","tokenized","xstock","shares"]):
            dropped += 1
            continue
        g.write(json.dumps(o, ensure_ascii=False) + "\n")
        kept += 1
tmp.replace(inp)
print(f"[READY] final_deny_actions: kept={kept} dropped={dropped}")
PY

# 4) final deny: no-data / low-liq / low-tx / low-vol
python scripts/final_deny_nodata_canonical.py
