#!/usr/bin/env bash
set -euo pipefail

cd /home/tng25/lino_FINAL_20260203_182626
source .venv/bin/activate

mkdir -p state

# --- wallet env ---
if [ -z "${KEYPAIR_PATH:-}" ]; then
  [ -f "keypair.json" ] && KEYPAIR_PATH="$(pwd)/keypair.json"
fi
if { [ -z "${WALLET_PUBKEY:-}" ] || [ -z "${TRADER_USER_PUBLIC_KEY:-}" ]; } \
    && [ -n "${KEYPAIR_PATH:-}" ] && [ -f "$KEYPAIR_PATH" ]; then
  _PK="$(python - <<PY
import json,sys
try:
    from solders.keypair import Keypair
    kp=Keypair.from_bytes(bytes(json.load(open("$KEYPAIR_PATH","r"))))
    print(str(kp.pubkey()))
except Exception:
    pass
PY
)"
  if [ -n "${_PK:-}" ]; then
    export WALLET_PUBKEY="${WALLET_PUBKEY:-$_PK}"
    export TRADER_USER_PUBLIC_KEY="${TRADER_USER_PUBLIC_KEY:-$_PK}"
    echo "WALLET_ENV: pubkey=$_PK keypair=$KEYPAIR_PATH"
  fi
fi

echo "🚀 FULL LIVE WITH BRAIN"

# --- Brain refresh loop ---
nohup bash -lc 'SLEEP_SEC="${SLEEP_SEC:-120}" ./scripts/brain_refresh_loop.sh' \
  > state/brain_refresh_loop.nohup.log 2>&1 &

sleep 1
echo "brain_refresh_loop pid(s):"
pgrep -af "scripts/brain_refresh_loop.sh" || true

# --- Wait for tradable file (max 120s) ---
READY_TRADABLE="state/ready_scored_tradable.jsonl"
echo "⏳ waiting for $READY_TRADABLE to exist and be non-empty (max 120s)"
for i in $(seq 1 120); do
  if [ -s "$READY_TRADABLE" ]; then
    echo "✅ ready: $READY_TRADABLE (lines=$(wc -l < "$READY_TRADABLE"))"
    break
  fi
  sleep 1
done

# if still not ready, fallback to ready_scored.jsonl (avoid hard stop)
if [ ! -s "$READY_TRADABLE" ]; then
  echo "⚠️ tradable not ready -> fallback READY_FILE=state/ready_scored.jsonl"
  export READY_FILE="state/ready_scored.jsonl"
else
  export READY_FILE="$READY_TRADABLE"
fi

# --- Trader loop ---
python -u src/run_live.py
