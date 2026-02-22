#!/usr/bin/env bash
# H24 watchdog: runs full_live_with_brain.sh, restarts on exit, logs per run.
# Stop cleanly by creating state/STOP file.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/tng25/lino_FINAL_20260203_182626}"
cd "$REPO_ROOT"

WATCHDOG_RESTART_DELAY="${WATCHDOG_RESTART_DELAY:-5}"
STOP_FILE="state/STOP"

mkdir -p state

echo "[h24_watchdog] started pid=$$ repo=$REPO_ROOT restart_delay=${WATCHDOG_RESTART_DELAY}s"
echo "[h24_watchdog] create '$STOP_FILE' to stop cleanly"

while true; do
  # Check for stop signal
  if [ -f "$STOP_FILE" ]; then
    echo "[h24_watchdog] STOP file detected -> exiting cleanly"
    exit 0
  fi

  # Create a dated log file for this run
  _ts="$(date +%Y%m%d_%H%M%S)"
  _log="state/h24_${_ts}.log"

  echo "[h24_watchdog] $(date -Is) starting full_live_with_brain.sh -> log: $_log"

  # Run the main script, tee output to dated log
  if bash "$REPO_ROOT/scripts/full_live_with_brain.sh" 2>&1 | tee -a "$_log"; then
    _exit_code=0
  else
    _exit_code=$?
  fi

  echo "[h24_watchdog] $(date -Is) full_live_with_brain.sh exited (code=$_exit_code)"

  # Check stop signal again before restarting
  if [ -f "$STOP_FILE" ]; then
    echo "[h24_watchdog] STOP file detected after exit -> exiting cleanly"
    exit 0
  fi

  echo "[h24_watchdog] restarting in ${WATCHDOG_RESTART_DELAY}s..."
  sleep "$WATCHDOG_RESTART_DELAY"
done
