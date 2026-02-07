#!/usr/bin/env bash
set -u  # pas -e sinon ça quitte

cd "$(dirname "$0")/.." || exit 0

source .venv/bin/activate
export PATH="$(pwd)/.venv/bin:$PATH"

mkdir -p state
RUN_LOG="state/run_live_FULL_$(date +%s).log"
BRAIN_LOG="state/brain_v2_$(date +%s).log"

# pubkey robuste
export WALLET_PUBKEY="$(
  python3 - <<'PY'
import json
from solders.keypair import Keypair
kp = Keypair.from_bytes(bytes(json.load(open("keypair.json"))))
print(str(kp.pubkey()))
PY
)"
export TRADER_USER_PUBLIC_KEY="$WALLET_PUBKEY"

# brain config
export BRAIN_READY_IN="${BRAIN_READY_IN:-state/ready_to_trade_scored.jsonl}"
export BRAIN_READY_OUT="${BRAIN_READY_OUT:-state/ready_scored.jsonl}"
export READY_FILE="${READY_FILE:-state/ready_scored.jsonl}"
export SKIP_MINTS_FILE="${SKIP_MINTS_FILE:-state/skip_mints.txt}"
export IGNORE_HOLDING_BELOW="${IGNORE_HOLDING_BELOW:-0.001}"
export BRAIN_TOP_N="${BRAIN_TOP_N:-70}"
export BRAIN_MIN_SCORE="${BRAIN_MIN_SCORE:--999999}"
export BRAIN_EVERY_SEC="${BRAIN_EVERY_SEC:-20}"

# run config
export MODE="${MODE:-FULL}"
export TRADER_DRY_RUN="${TRADER_DRY_RUN:-0}"

echo "[LAUNCH] PYTHON=$(which python3)" | tee -a "$RUN_LOG"
python3 -V | tee -a "$RUN_LOG"
echo "[LAUNCH] WALLET_PUBKEY=$WALLET_PUBKEY" | tee -a "$RUN_LOG"
echo "[LAUNCH] MODE=$MODE TRADER_DRY_RUN=$TRADER_DRY_RUN READY_FILE=$READY_FILE" | tee -a "$RUN_LOG"
echo "[LAUNCH] brain every ${BRAIN_EVERY_SEC}s -> $BRAIN_LOG" | tee -a "$RUN_LOG"
echo "[LAUNCH] run_live -> $RUN_LOG" | tee -a "$RUN_LOG"

# brain loop en background (jamais fatal)
(
  while true; do
    echo "[BRAIN] tick $(date -Is)" >>"$BRAIN_LOG"
    python3 -u src/brain/brain_loop_v2.py >>"$BRAIN_LOG" 2>&1 || echo "[BRAIN] error ignored $(date -Is)" >>"$BRAIN_LOG"
    sleep "$BRAIN_EVERY_SEC"
  done
) &

# run_live en boucle (si crash, restart)
while true; do
  echo "[RUN] starting run_live $(date -Is)" | tee -a "$RUN_LOG"
  python3 -u src/run_live.py >>"$RUN_LOG" 2>&1
  ec=$?
  echo "[RUN] run_live exited code=$ec $(date -Is) (restart in 3s)" | tee -a "$RUN_LOG"
  sleep 3
done
