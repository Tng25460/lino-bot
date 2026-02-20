#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

# load perf/env if present
source scripts/env_perf.sh || true
[[ -f state/env_override.sh ]] && source state/env_override.sh

# REQUIRED: READY_FILE must exist and be non-empty
: "${READY_FILE:?export READY_FILE=state/ready_tradable.jsonl}"
if [ ! -s "$READY_FILE" ]; then
  echo "[FATAL] READY_FILE missing/empty: $READY_FILE"
  exit 2
fi

# export wallet pubkey if missing (python+solders, no solana-cli needed)
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

echo "[READY] external READY_FILE=$READY_FILE (lines=$(wc -l < "$READY_FILE"))"
echo "[WALLET] WALLET_PUBKEY=${WALLET_PUBKEY:-"(missing)"} TRADER_USER_PUBLIC_KEY=${TRADER_USER_PUBLIC_KEY:-"(missing)"}"

# logs
ts="$(date +%Y%m%d_%H%M%S)"
export RUNLIVE_LOG="${RUNLIVE_LOG:-state/run_live_EXTERNAL_${ts}.log}"
export BRAIN_LOG="${BRAIN_LOG:-state/brain_EXTERNAL_${ts}.log}"

echo "🚀 EXTERNAL READY: brain + run_live"
echo "   READY_FILE=$READY_FILE"
echo "   RUNLIVE_LOG=$RUNLIVE_LOG"
echo "   BRAIN_LOG=$BRAIN_LOG"

# pick brain entry if present (optional)
brain_entry=""
for cand in \
  "src/brain_loop_v2.py" \
  "src/brain/brain_loop_v2.py" \
  "src/brain_loop.py" \
  "src/brain/brain_loop.py"
do
  if [ -f "$cand" ]; then brain_entry="$cand"; break; fi
done

brain_pid=""
if [ -n "$brain_entry" ]; then
  echo "[BRAIN] start $brain_entry"
  ./.venv/bin/python -u "$brain_entry" 2>&1 | tee -a "$BRAIN_LOG" &
  brain_pid="$!"
else
  echo "[BRAIN] skipped (no brain loop found)"
fi

# start run_live (foreground)
set +e
./.venv/bin/python -u src/run_live.py 2>&1 | tee -a "$RUNLIVE_LOG"
rc=${PIPESTATUS[0]}
set -e

echo "[run_live exited] rc=$rc -> stopping brain pid=${brain_pid:-none}"
if [ -n "${brain_pid:-}" ]; then
  kill "$brain_pid" 2>/dev/null || true
  wait "$brain_pid" 2>/dev/null || true
fi
exit "$rc"
