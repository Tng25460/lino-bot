#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1
source .venv/bin/activate

PY="$(which python3)"
echo "[LAUNCH] PYTHON=$PY"
$PY -V

TS="$(date +%s)"
MODE="${MODE:-FULL}"
LOG_BRAIN="state/brain_${TS}.log"
LOG_LIVE="state/run_live_${MODE}_${TS}.log"
mkdir -p state

echo "[LAUNCH] WALLET_PUBKEY=${WALLET_PUBKEY:-}"
echo "[LAUNCH] MODE=$MODE TRADER_DRY_RUN=${TRADER_DRY_RUN:-} READY_FILE=${READY_FILE:-}"
echo "[LAUNCH] brain -> src/brain/brain_loop.py (every 20s) -> $LOG_BRAIN"
echo "[LAUNCH] run_live -> $LOG_LIVE"

( while true; do
    $PY -u src/brain/brain_loop.py >> "$LOG_BRAIN" 2>&1 || true
    sleep 20
  done ) &

echo "[RUN] starting run_live $(date -Iseconds)" | tee -a "$LOG_LIVE"
while true; do
  $PY -u src/run_live.py >> "$LOG_LIVE" 2>&1 || true
  echo "[RUN] run_live exited code=$? $(date -Iseconds) (restart in 3s)" | tee -a "$LOG_LIVE"
  sleep 3
done
