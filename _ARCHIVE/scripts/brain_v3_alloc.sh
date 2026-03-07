#!/usr/bin/env bash
set -e

STATS="state/brain_v3_stats.json"
if [ ! -f "$STATS" ]; then
  echo "No brain stats"
  exit 0
fi

WINRATE=$(python - <<PY
import json
d=json.load(open("state/brain_v3_stats.json"))
p=d.get("PUMP",{})
print(p.get("winrate_pct",0))
PY
)

BASE=0.0025

if (( $(echo "$WINRATE > 60" | bc -l) )); then
  NEW=$(echo "$BASE * 1.5" | bc -l)
elif (( $(echo "$WINRATE < 40" | bc -l) )); then
  NEW=$(echo "$BASE * 0.6" | bc -l)
else
  NEW=$BASE
fi

tmp="/tmp/live.env.$$"
grep -v '^export BUY_AMOUNT_SOL=' state/live.env > "$tmp" || true
echo "export BUY_AMOUNT_SOL=$NEW" >> "$tmp"
mv "$tmp" state/live.env

echo "NEW BUY_AMOUNT_SOL=$NEW (winrate=$WINRATE)"
