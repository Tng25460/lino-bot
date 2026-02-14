#!/usr/bin/env bash
set -euo pipefail
cd /home/tng25/lino_FINAL_20260203_182626 || exit 1
source .venv/bin/activate || exit 1
source scripts/env_perf.sh

# trader: plus rapide
export JUP_MIN_QUOTE_INTERVAL_S="${JUP_MIN_QUOTE_INTERVAL_S_TRADER:-3.0}"
export JUP_MIN_QUOTE_INTERVAL_MIN_S="${JUP_MIN_QUOTE_INTERVAL_MIN_S_TRADER:-2.0}"
export JUP_MIN_QUOTE_INTERVAL_MAX_S="${JUP_MIN_QUOTE_INTERVAL_MAX_S_TRADER:-10.0}"

# wallet
export KEYPAIR="${KEYPAIR:-/home/tng25/lino_FINAL_20260203_182626/keypair.json}"
if [[ -z "${WALLET_PUBKEY:-}" && -z "${TRADER_USER_PUBLIC_KEY:-}" ]]; then
  if command -v solana >/dev/null 2>&1; then
    export WALLET_PUBKEY="$(solana-keygen pubkey "$KEYPAIR" 2>/dev/null || true)"
  fi
fi
export TRADER_USER_PUBLIC_KEY="${TRADER_USER_PUBLIC_KEY:-${WALLET_PUBKEY:-}}"

echo "WALLET_PUBKEY=${WALLET_PUBKEY:-}"
echo "TRADER_USER_PUBLIC_KEY=${TRADER_USER_PUBLIC_KEY:-}"
echo "KEYPAIR=$KEYPAIR"

python -u src/run_live.py
