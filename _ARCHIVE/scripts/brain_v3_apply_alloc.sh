#!/usr/bin/env bash
set -e
FILE="state/brain_v3_alloc.json"
[ -f "$FILE" ] || exit 0
VAL=$(python -c "import json; d=json.load(open(\"state/brain_v3_alloc.json\")); print(max(d.values()))")
tmp="/tmp/live.env.$$"
grep -v "^export BUY_AMOUNT_SOL=" state/live.env > "$tmp" 2>/dev/null || true
echo "export BUY_AMOUNT_SOL=$VAL" >> "$tmp"
mv "$tmp" state/live.env
echo "BUY_AMOUNT_SOL updated to $VAL"
