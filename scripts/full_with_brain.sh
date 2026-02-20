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

# --- wallet env ---
if [ -z "${KEYPAIR_PATH:-}" ]; then
  [ -f "keypair.json" ] && KEYPAIR_PATH="$(pwd)/keypair.json"
fi
if { [ -z "${WALLET_PUBKEY:-}" ] || [ -z "${TRADER_USER_PUBLIC_KEY:-}" ]; } \
    && [ -n "${KEYPAIR_PATH:-}" ] && [ -f "$KEYPAIR_PATH" ]; then
  _PK="$(python - <<PY2
import json,sys
try:
    from solders.keypair import Keypair
    kp=Keypair.from_bytes(bytes(json.load(open("$KEYPAIR_PATH","r"))))
    print(str(kp.pubkey()))
except Exception:
    pass
PY2
)"
  if [ -n "${_PK:-}" ]; then
    export WALLET_PUBKEY="${WALLET_PUBKEY:-$_PK}"
    export TRADER_USER_PUBLIC_KEY="${TRADER_USER_PUBLIC_KEY:-$_PK}"
    echo "WALLET_ENV: pubkey=$_PK keypair=$KEYPAIR_PATH"
  fi
fi

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
