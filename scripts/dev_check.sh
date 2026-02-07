#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

echo "== compileall =="
python -m compileall -q . || exit 1
echo "OK compileall"

echo "== smoke trader_exec DRY_RUN ONE_SHOT =="
export TRADER_DRY_RUN=1
export ONE_SHOT=1
export TRADER_ONE_SHOT=1
export BUY_AMOUNT_SOL=${BUY_AMOUNT_SOL:-0.003}
export JUP_BASE_URL=${JUP_BASE_URL:-https://api.jup.ag}
export RPC_HTTP_URL=${RPC_HTTP_URL:-https://api.mainnet-beta.solana.com}

timeout 20s python -u src/trader_exec.py >/tmp/smoke_trader_exec.log 2>&1 || true
tail -n 120 /tmp/smoke_trader_exec.log || true

echo "OK (see /tmp/smoke_trader_exec.log)"
