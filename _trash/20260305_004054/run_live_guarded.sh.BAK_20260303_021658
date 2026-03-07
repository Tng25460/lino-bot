#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

LOCK_FILE="${LOCK_FILE:-state/run_live.lock}"
ENV_FILE="${ENV_FILE:-state/live.env}"
LOG_DIR="${LOG_DIR:-logs}"
LOG_KEEP_DAYS="${LOG_KEEP_DAYS:-7}"

mkdir -p "$LOG_DIR" state
find "$LOG_DIR" -type f -name "run_live_*.log" -mtime +"$LOG_KEEP_DAYS" -delete 2>/dev/null || true

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "⛔ run_live déjà en cours (lock=$LOCK_FILE)"
  exit 23
fi

set -a
[ -f "$ENV_FILE" ] && source "$ENV_FILE"
set +a

export PYTHONPATH="src:${PYTHONPATH:-}"

# FORCE CANONICAL
# READY_FILE comes from state/live.env (if set) else fallback to canonical
export READY_FILE="${READY_FILE:-state/READY_CANONICAL.jsonl}"
export TRADER_READY_FILE="$READY_FILE"

# force skip file safe (jamais /dev/null)
export SKIP_MINTS_FILE="${SKIP_MINTS_FILE:-state/skip_mints_trader.txt}"
export TRADER_SKIP_MINTS_FILE="${TRADER_SKIP_MINTS_FILE:-$SKIP_MINTS_FILE}"
if [ "$SKIP_MINTS_FILE" = "/dev/null" ]; then export SKIP_MINTS_FILE="state/skip_mints_trader.txt"; fi
if [ "$TRADER_SKIP_MINTS_FILE" = "/dev/null" ]; then export TRADER_SKIP_MINTS_FILE="$SKIP_MINTS_FILE"; fi

LOG="$LOG_DIR/run_live_$(date +%Y%m%d_%H%M%S).log"
echo "▶️ START run_live @ $(date +%Y%m%d_%H%M%S) READY_FILE=$READY_FILE SKIP_MINTS_FILE=$SKIP_MINTS_FILE TRADER_SKIP_MINTS_FILE=$TRADER_SKIP_MINTS_FILE" | tee -a "$LOG"

# Backoff si "no candidates" (évite spam CPU/logs)
NO_CAND_BACKOFF_S="${NO_CAND_BACKOFF_S:-60}"
(
  ./.venv/bin/python -u src/run_live.py 2>&1 || true
) | tee -a "$LOG" | awk -v b="$NO_CAND_BACKOFF_S" '
  { print; fflush(); }
  /no candidates after ready filter/ { system("sleep " b); }
'
