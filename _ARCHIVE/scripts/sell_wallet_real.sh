#!/usr/bin/env bash
set -euo pipefail

cd /home/tng25/lino_FINAL_20260203_182626 || exit 1
source .venv/bin/activate || exit 1

# On configure via ENV (car sell_exec_wrap.py / sell_exec.py n'acceptent pas tes flags)
export RPC_HTTP="${RPC_HTTP:-https://api.mainnet-beta.solana.com}"
export JUP_BASE_URL="${JUP_BASE_URL:-https://lite-api.jup.ag}"

export SLIPPAGE_BPS="${SLIPPAGE_BPS:-400}"
export MAX_PRICE_IMPACT_PCT="${MAX_PRICE_IMPACT_PCT:-6.0}"

export SELL_SLEEP_BETWEEN="${SELL_SLEEP_BETWEEN:-4}"

LOG="${LOG:?missing LOG env var}"

echo "[INFO] start $(date -Is)" | tee -a "$LOG"
echo "[INFO] rpc=$RPC_HTTP jup=$JUP_BASE_URL slip=$SLIPPAGE_BPS impact=$MAX_PRICE_IMPACT_PCT sleep=$SELL_SLEEP_BETWEEN" | tee -a "$LOG"

# spl-token accounts: on prend (mint, ui) où ui != 0
spl-token accounts --url "$RPC_HTTP" \
| awk 'NR>2 && $1 ~ /^[1-9A-HJ-NP-Za-km-z]{32,44}$/ && $2!="0" {print $1,$2}' \
| while read -r MINT UI; do
    # ne pas "vendre" SOL
    if [ "$MINT" = "So11111111111111111111111111111111111111112" ]; then
      continue
    fi

    echo "[SELL] mint=$MINT ui=$UI" | tee -a "$LOG"

    /home/tng25/lino_FINAL_20260203_182626/.venv/bin/python -u src/sell_exec_wrap.py \
      --mint "$MINT" \
      --ui "$UI" \
      --reason "sell_wallet_reset" \
      2>&1 | tee -a "$LOG"

    echo "[DONE] mint=$MINT" | tee -a "$LOG"
    sleep "$SELL_SLEEP_BETWEEN"
  done

echo "[INFO] end $(date -Is)" | tee -a "$LOG"
