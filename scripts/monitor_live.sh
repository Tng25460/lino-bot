#!/usr/bin/env bash
# Live monitor: shows key stats + filtered log tail from the running bot.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/tng25/lino_FINAL_20260203_182626}"
cd "$REPO_ROOT" 2>/dev/null || true

echo "=== lino-bot monitor $(date -Is) ==="
echo ""

# --- PIDs ---
echo "--- Active processes ---"
for P in "h24_watchdog.sh" "full_live_with_brain.sh" "brain_refresh_loop.sh" "run_live.py" "trader_exec.py"; do
  PIDS=$(pgrep -f "$P" 2>/dev/null | tr '\n' ' ' || true)
  printf "  %-35s %s\n" "$P" "${PIDS:-[NOT RUNNING]}"
done
echo ""

# --- Watchdog PID file ---
if [ -f "state/h24_watchdog.pid" ]; then
  _wpid=$(cat state/h24_watchdog.pid 2>/dev/null || true)
  if [ -n "$_wpid" ] && kill -0 "$_wpid" 2>/dev/null; then
    echo "  h24_watchdog pid=$_wpid (alive)"
  else
    echo "  h24_watchdog pid=$_wpid (dead/stale)"
  fi
fi
echo ""

# --- Ready files ---
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
    printf "  %-55s lines=%-5s%s\n" "$F" "$LINES" "$AGE"
  else
    printf "  %-55s MISSING\n" "$F"
  fi
done
echo ""

# --- RL_SKIP ---
echo "--- RL_SKIP state ---"
RL_FILE="state/rl_skip_mints.json"
if [ -f "$RL_FILE" ]; then
  python3 -c "
import json, time
try:
    d = json.load(open('$RL_FILE'))
    now = int(time.time())
    active = [m for m, v in d.items() if int(v) > now]
    print(f'  active_rl_skip={len(active)} total={len(d)} top5={active[:5]}')
except Exception as e:
    print(f'  rl_skip read error: {e}')
" 2>/dev/null || echo "  rl_skip: error reading"
fi
echo ""

# --- Recent buy/sell events ---
echo "--- Recent events (last 20 lines) ---"
_log=""
for F in state/run_live.nohup.log state/h24_*.log; do
  if [ -f "$F" ]; then
    _log="$F"
    break
  fi
done 2>/dev/null || true

if [ -n "$_log" ] && [ -f "$_log" ]; then
  echo "  Log: $_log"
  tail -n 100 "$_log" 2>/dev/null | grep -a \
    -e "BUY\|SELL\|PICK\|EXEC_RC\|429\|RL_SKIP\|SKIP\|HOLD\|PROFILE\|txsig\|NO_BUY\|backoff\|❌\|✅\|⚠️\|🧊\|⏸️\|🎯\|⏭️" \
    | tail -20 || true
else
  echo "  No log file found"
fi
echo ""

# --- HIST_BAD env ---
echo "--- HIST_BAD config ---"
echo "  DISABLE_HIST_BAD=${DISABLE_HIST_BAD:-0}"
echo "  HIST_SKIP_MIN_N=${HIST_SKIP_MIN_N:-3}"
echo "  HIST_SKIP_AVG_PNL_MAX=${HIST_SKIP_AVG_PNL_MAX:-0.0}"
echo "  HIST_SKIP_EPSILON=${HIST_SKIP_EPSILON:-1e-6}"
echo ""
echo "  QUOTE_429_COOLDOWN_SEC=${QUOTE_429_COOLDOWN_SEC:-300}"
echo "  CANDIDATE_TRIES=${CANDIDATE_TRIES:-10}"
