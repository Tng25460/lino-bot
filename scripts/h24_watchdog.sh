#!/usr/bin/env bash
# H24 watchdog: runs full_live_with_brain.sh, restarts on exit, logs per run.
# Stop cleanly by creating state/STOP file.
# Singleton: enforced via flock (atomic, race-condition-free, no stale-pid risk).
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/tng25/lino_FINAL_20260203_182626}"
cd "$REPO_ROOT"

WATCHDOG_RESTART_DELAY="${WATCHDOG_RESTART_DELAY:-5}"
STOP_FILE="state/STOP"
LOCK_FILE="state/h24_watchdog.lock"

mkdir -p state

# --- Singleton guard via flock ---
# We re-exec ourselves under flock so the lock is held for the lifetime of the process.
# FD 200 is used for the lock; flock -n fails immediately if already locked.
if [ "${_H24_LOCKED:-}" != "1" ]; then
  exec env _H24_LOCKED=1 flock -n "$LOCK_FILE" "$0" "$@"
  # exec replaces this process; code below only runs in the locked instance
fi
# If we reach here, we hold the flock lock.
echo "[h24_watchdog] singleton lock acquired (flock $LOCK_FILE) pid=$$"
# --- /Singleton guard ---

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
