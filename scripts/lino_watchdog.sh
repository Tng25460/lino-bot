#!/usr/bin/env bash
# Watchdog: ensures brain_refresh_loop and run_live stay alive (no duplicates)
# Started by start_h24.sh inside a tmux session.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/tng25/lino_FINAL_20260203_182626}"
cd "$REPO_ROOT"
source .venv/bin/activate

WATCHDOG_INTERVAL="${WATCHDOG_INTERVAL:-30}"
SLEEP_SEC="${SLEEP_SEC:-120}"
export SLEEP_SEC

mkdir -p state

echo "[watchdog] started pid=$$ repo=$REPO_ROOT interval=${WATCHDOG_INTERVAL}s"

# Write pid file so stop_all.sh can kill us too
echo $$ > state/watchdog.pid

_ensure_brain() {
  if ! pgrep -f "brain_refresh_loop.sh" > /dev/null 2>&1; then
    echo "[watchdog] brain_refresh_loop not running -> starting"
    nohup bash "$REPO_ROOT/scripts/brain_refresh_loop.sh" \
      >> state/brain_refresh_loop.nohup.log 2>&1 &
    echo "[watchdog] brain_refresh_loop started pid=$!"
  fi
}

_ensure_run_live() {
  if ! pgrep -f "run_live.py" > /dev/null 2>&1; then
    echo "[watchdog] run_live.py not running -> starting"
    # Wait up to 60s for tradable file before starting run_live
    READY_TRADABLE="state/ready_scored_tradable.jsonl"
    for _i in $(seq 1 60); do
      if [ -s "$READY_TRADABLE" ]; then
        break
      fi
      sleep 1
    done
    if [ -s "$READY_TRADABLE" ]; then
      export READY_FILE="$READY_TRADABLE"
    elif [ -s "state/ready_scored.jsonl" ]; then
      echo "[watchdog] tradable not ready -> fallback READY_FILE=state/ready_scored.jsonl"
      export READY_FILE="state/ready_scored.jsonl"
    fi
    nohup python -u "$REPO_ROOT/src/run_live.py" \
      >> state/run_live.nohup.log 2>&1 &
    echo "[watchdog] run_live started pid=$!"
  fi
}

while true; do
  _ensure_brain
  _ensure_run_live
  sleep "$WATCHDOG_INTERVAL"
done
