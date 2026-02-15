#!/usr/bin/env python3
import json, os, time
from pathlib import Path

p = Path(os.getenv("RL_SKIP_FILE","state/rl_skip_mints.json"))
now = int(time.time())

try:
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if not isinstance(d, dict):
        d = {}
except Exception:
    d = {}

out = {}
for k, v in (d or {}).items():
    k = str(k).strip()
    if not k:
        continue
    try:
        until = int(v)
    except Exception:
        continue
    if until > now:
        out[k] = until

p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(out, separators=(",",":")), encoding="utf-8")
print(f"[OK] rlskip_clean file={p} now={now} kept={len(out)} removed={len(d)-len(out)}")
