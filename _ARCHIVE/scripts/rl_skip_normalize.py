import json, time
from pathlib import Path

p = Path("state/rl_skip_mints.json")
if not p.exists():
    print("NO rl_skip_mints.json")
    raise SystemExit(0)

raw = p.read_text(encoding="utf-8", errors="ignore").strip()
d = json.loads(raw or "{}")
now = time.time()

out = {}
legacy = 0
kept = 0

for mint, v in (d or {}).items():
    # legacy format: mint -> something (string/int/...)
    if not isinstance(v, dict):
        legacy += 1
        # convert to expired entry (until=0) so it won't filter anything
        out[mint] = {"until": 0, "reason": "legacy_normalized"}
        continue

    until = float(v.get("until", 0) or 0)
    reason = str(v.get("reason", ""))
    # keep dict shape; if expired, force until=0
    if until <= now:
        out[mint] = {"until": 0, "reason": reason or "expired"}
    else:
        out[mint] = {"until": until, "reason": reason or "active"}
        kept += 1

p.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
print(f"OK normalize: legacy={legacy} active_kept={kept} total={len(out)}")
