#!/usr/bin/env bash

# --- load live env (propagate to all child processes) ---
if [ -f state/live.env ]; then
  set -a
  . state/live.env
  set +a
fi
# --- /load live env ---
set -euo pipefail

# --- H24 SINGLETON LOCK (prevents 2 watchdogs) ---
LOCK_FILE="${LOCK_FILE:-state/h24_watchdog.lock}"
mkdir -p state
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "[watchdog] another instance is running (lock=${LOCK_FILE}) -> exit" >&2
  exit 0
fi


cd /home/tng25/lino_FINAL_20260203_182626
source .venv/bin/activate

# Inputs
export READY_FILE="${READY_FILE:-state/ready_scored_tradable.jsonl}"
export MIN_TRADABLE_LINES="${MIN_TRADABLE_LINES:-30}"

# Trading safety
export ALLOW_REBUY_SAME_MINT="${ALLOW_REBUY_SAME_MINT:-0}"
export AUTOSKIP_ALREADY_HOLDING="${AUTOSKIP_ALREADY_HOLDING:-0}"
export QUOTE_429_COOLDOWN_SEC="${QUOTE_429_COOLDOWN_SEC:-900}"

# Restart backoff
SLEEP_ON_EXIT="${SLEEP_ON_EXIT:-5}"

mkdir -p state

while true; do
  LOG="state/h24_$(date +%Y%m%d_%H%M%S).log"
  echo "[watchdog] starting full_live_with_brain -> $LOG"
  bash scripts/full_live_with_brain.sh >"$LOG" 2>&1 || true
  rc=$?
  echo "[watchdog] exited rc=$rc sleeping ${SLEEP_ON_EXIT}s"
  sleep "${SLEEP_ON_EXIT}"
done
