#!/usr/bin/env bash
set -euo pipefail
cd /home/tng25/lino_FINAL_20260203_182626 || exit 1
source .venv/bin/activate || exit 1

RPC_HTTP="${RPC_HTTP:-https://api.mainnet-beta.solana.com}"
JUP_BASE_URL="${JUP_BASE_URL:-https://lite-api.jup.ag}"
SLIPPAGE_BPS="${SLIPPAGE_BPS:-400}"
MAX_PRICE_IMPACT_PCT="${MAX_PRICE_IMPACT_PCT:-6.0}"
SELL_SLEEP_BETWEEN="${SELL_SLEEP_BETWEEN:-4}"
DUST_UI_MIN="${DUST_UI_MIN:-0.00001}"

LOG="${LOG:?missing LOG env var}"

echo "[INFO] start $(date -Is)" | tee -a "$LOG"
echo "[INFO] rpc=$RPC_HTTP jup=$JUP_BASE_URL slip=$SLIPPAGE_BPS impact=$MAX_PRICE_IMPACT_PCT sleep=$SELL_SLEEP_BETWEEN dust_ui_min=$DUST_UI_MIN" | tee -a "$LOG"

# spl-token accounts:
# Token                                         Balance
# <MINT>                                        <UI>
spl-token accounts --url "$RPC_HTTP" \
| awk -v d="$DUST_UI_MIN" '
  NR>2 && $1 ~ /^[1-9A-HJ-NP-Za-km-z]{32,44}$/ {
    mint=$1; ui=$2+0;
    if (ui>0) print mint, ui
  }' \
| while read -r mint ui; do
    if python - <<PY
u=float("$ui")
print("OK" if u < float("$DUST_UI_MIN") else "NO")
PY
    then
      :
    fi

    # dust => try close ATA (best-effort) then continue
    if python - <<PY
u=float("$ui")
import sys
sys.exit(0 if u < float("$DUST_UI_MIN") else 1)
PY
    then
      echo "[DUST] mint=$mint ui=$ui -> try close ATA" | tee -a "$LOG"
      spl-token close "$mint" --url "$RPC_HTTP" 2>&1 | sed 's/^/  /' | tee -a "$LOG" || true
      echo "[DONE] mint=$mint (dust_closed)" | tee -a "$LOG"
      sleep "$SELL_SLEEP_BETWEEN"
      continue
    fi

    echo "[SELL] mint=$mint ui=$ui" | tee -a "$LOG"

    # sell_exec_wrap reads env: RPC_HTTP, JUP_BASE_URL, SLIPPAGE_BPS, MAX_PRICE_IMPACT_PCT
    RPC_HTTP="$RPC_HTTP" JUP_BASE_URL="$JUP_BASE_URL" SLIPPAGE_BPS="$SLIPPAGE_BPS" MAX_PRICE_IMPACT_PCT="$MAX_PRICE_IMPACT_PCT" \
      python -u src/sell_exec_wrap.py --mint "$mint" --ui "$ui" --reason "sell_wallet_reset" 2>&1 | tee -a "$LOG" || true

    echo "[DONE] mint=$mint (attempted)" | tee -a "$LOG"
    sleep "$SELL_SLEEP_BETWEEN"
  done

echo "[INFO] end $(date -Is)" | tee -a "$LOG"
