#!/usr/bin/env bash
set -u  # PAS de -e : on ne veut jamais quitter en live
cd "$(dirname "$0")/.." || exit 0

# venv
source .venv/bin/activate
export PATH="$(pwd)/.venv/bin:$PATH"

mkdir -p state
RUN_LOG="state/run_live_FULL_$(date +%s).log"
BRAIN_LOG="state/brain_loop_$(date +%s).log"

# wallet pubkey (robuste)
export WALLET_PUBKEY="$(
  python3 - <<'PY'
import json
from solders.keypair import Keypair
kp = Keypair.from_bytes(bytes(json.load(open("keypair.json"))))
print(str(kp.pubkey()))
PY
)"
export TRADER_USER_PUBLIC_KEY="$WALLET_PUBKEY"

# config (tu peux override avant de lancer)
export MODE="${MODE:-FULL}"
export TRADER_DRY_RUN="${TRADER_DRY_RUN:-0}"
export READY_FILE="${READY_FILE:-state/ready_scored.jsonl}"
export BRAIN_EVERY_SEC="${BRAIN_EVERY_SEC:-20}"

echo "[LAUNCH] PYTHON=$(which python3)" | tee -a "$RUN_LOG"
python3 -V | tee -a "$RUN_LOG"
echo "[LAUNCH] WALLET_PUBKEY=$WALLET_PUBKEY" | tee -a "$RUN_LOG"
echo "[LAUNCH] MODE=$MODE TRADER_DRY_RUN=$TRADER_DRY_RUN READY_FILE=$READY_FILE" | tee -a "$RUN_LOG"
echo "[LAUNCH] brain every ${BRAIN_EVERY_SEC}s -> $BRAIN_LOG" | tee -a "$RUN_LOG"
echo "[LAUNCH] run_live -> $RUN_LOG" | tee -a "$RUN_LOG"

cleanup() {
  echo "[LAUNCH] stopping..." | tee -a "$RUN_LOG"
  [[ -n "${BRAIN_PID:-}" ]] && kill "$BRAIN_PID" 2>/dev/null || true
  pkill -f "python3 -u src/run_live.py" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# cerveau loop (ignore errors, never quit)
(
  while true; do
    echo "[BRAIN] tick $(date -Is)" | tee -a "$BRAIN_LOG"
    python3 -u src/brain/brain_loop.py >>"$BRAIN_LOG" 2>&1 || echo "[BRAIN] error ignored $(date -Is)" >>"$BRAIN_LOG"
    sleep "$BRAIN_EVERY_SEC"
  done
) &
BRAIN_PID=$!

# run_live loop (restart on crash)
while true; do
  echo "[RUN] starting run_live $(date -Is)" | tee -a "$RUN_LOG"
  python3 -u src/run_live.py >>"$RUN_LOG" 2>&1
  EC=$?
  echo "[RUN] run_live exited code=$EC at $(date -Is) (restart in 3s)" | tee -a "$RUN_LOG"
  sleep 3
done
