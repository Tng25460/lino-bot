#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

PID="$(pgrep -f "src/run_live.py" | head -n1 || true)"
if [[ -z "${PID:-}" ]]; then
  echo "run_live.py: NOT RUNNING"
  exit 0
fi

echo "PID=$PID"
echo
echo "--- ENV RUNTIME ---"
tr '\0' '\n' < /proc/$PID/environ | rg '^(MODE|BUY_AMOUNT_SOL|TRADER_DRY_RUN|SELL_DRY_RUN|STRICT_ONLY|ROUTE_GATE_MODE|JUP_DEX_FALLBACK_ANY|SLIPPAGE_BPS|MAX_PRICE_IMPACT_PCT|MAX_TRADES_PER_HOUR|COOLDOWN_SEC|MAX_ACTIVE_POSITIONS|SELL_FORCE_ALL|TRADER_SKIP_MINTS_FILE|HOLDING_SKIP_SEC|RL_SKIP_SEC|MIN_SOL_BUFFER_SOL)=' | sort || true

echo
echo "--- PROCESS ---"
pgrep -af "src/run_live.py|run_live_guarded.sh|watchdog_supervisor.sh" || true

echo
echo "--- LATEST LOG ---"
LATEST="$(ls -1t logs/run_live*.log 2>/dev/null | head -n1 || true)"
echo "${LATEST:-no_log}"
if [[ -n "${LATEST:-}" ]]; then
  tail -n 80 "$LATEST" | rg -n "START run_live|SELL_TICK|ready_count|pick=|sent txsig=|recorded BUY|already holding|TOKEN_NOT_TRADABLE|quote failed|TRADER_EXEC_RC|TP1|TP2|HARD_SL|SOLD" || true
fi

echo
echo "--- SQLITE LAST 15 ---"
sqlite3 state/trades.sqlite "select rowid, ts, side, mint, substr(txsig,1,16) from trades order by rowid desc limit 15;" || true
