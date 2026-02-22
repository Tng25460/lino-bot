#!/usr/bin/env bash
# Show bot status: PIDs, key counters, ready file line counts
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/tng25/lino_FINAL_20260203_182626}"
cd "$REPO_ROOT" 2>/dev/null || true

echo "=== lino-bot status $(date -Is) ==="

echo ""
echo "--- PIDs ---"
for PATTERN in "lino_watchdog.sh" "brain_refresh_loop.sh" "run_live.py" "trader_exec.py"; do
  PIDS=$(pgrep -f "$PATTERN" 2>/dev/null | tr '\n' ' ' || true)
  printf "  %-30s %s\n" "$PATTERN" "${PIDS:-[NOT RUNNING]}"
done

echo ""
echo "--- Ready files ---"
for F in state/ready_scored.jsonl state/ready_scored_tradable.jsonl state/ready_scored_tradable.lastgood.jsonl; do
  if [ -f "$F" ]; then
    LINES=$(wc -l < "$F" 2>/dev/null || echo "?")
    AGE=""
    if command -v stat >/dev/null 2>&1; then
      MOD=$(stat -c %Y "$F" 2>/dev/null || echo 0)
      NOW=$(date +%s)
      AGE=" age=$(( NOW - MOD ))s"
    fi
    printf "  %-52s lines=%-5s%s\n" "$F" "$LINES" "$AGE"
  else
    printf "  %-52s MISSING\n" "$F"
  fi
done

echo ""
echo "--- RL_SKIP ---"
RL_FILE="state/rl_skip_mints.json"
if [ -f "$RL_FILE" ]; then
  python3 -c "
import json,time
try:
    d=json.load(open('$RL_FILE'))
    now=int(time.time())
    active=[m for m,v in d.items() if int(v)>now]
    print(f'  active_rl_skip={len(active)} total={len(d)}')
except Exception as e:
    print(f'  rl_skip read error: {e}')
" 2>/dev/null || echo "  rl_skip: error reading"
else
  echo "  rl_skip: file missing"
fi

echo ""
echo "--- Skip mints ---"
SKIP_FILE="state/skip_mints_trader.txt"
if [ -f "$SKIP_FILE" ]; then
  LINES=$(wc -l < "$SKIP_FILE" 2>/dev/null || echo 0)
  echo "  $SKIP_FILE lines=$LINES"
else
  echo "  $SKIP_FILE: missing"
fi

echo ""
echo "--- Last log lines (run_live.nohup.log) ---"
if [ -f "state/run_live.nohup.log" ]; then
  tail -5 state/run_live.nohup.log 2>/dev/null || true
fi
echo ""
