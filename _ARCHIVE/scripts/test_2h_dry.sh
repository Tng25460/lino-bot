#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="${REPO_ROOT:-/home/tng25/lino_FINAL_20260203_182626}"
cd "$REPO_ROOT" || exit 1
source .venv/bin/activate || true

# ---- CONFIG (safe) ----
export WALLET_PUBKEY="${WALLET_PUBKEY:-9U69xxU9eWRebdQ99FSo2FBwfafQZYjL4DT6ZFLqwmga}"
export TRADER_USER_PUBLIC_KEY="${TRADER_USER_PUBLIC_KEY:-$WALLET_PUBKEY}"
export KEYPAIR_PATH="${KEYPAIR_PATH:-/home/tng25/lino_FINAL_20260203_182626/keypair.json}"

export TRADER_DRY_RUN="${TRADER_DRY_RUN:-1}"
export READY_FILE="${READY_FILE:-state/ready_scored_tradable.jsonl}"

export BUY_AMOUNT_SOL="${BUY_AMOUNT_SOL:-0.003}"
export MIN_SOL_BUFFER_SOL="${MIN_SOL_BUFFER_SOL:-0.12}"
export SLIPPAGE_BPS="${SLIPPAGE_BPS:-300}"
export MAX_PRICE_IMPACT_PCT="${MAX_PRICE_IMPACT_PCT:-4.0}"
export STRICT_ONLY="${STRICT_ONLY:-1}"
export ROUTE_GATE_MODE="${ROUTE_GATE_MODE:-any}"

export NO_BUY_BACKOFF_SEC="${NO_BUY_BACKOFF_SEC:-60}"
export MIN_TRADABLE_LINES="${MIN_TRADABLE_LINES:-20}"
export DISABLE_HIST_BAD="${DISABLE_HIST_BAD:-1}"

DUR_SEC="${DUR_SEC:-7200}"  # 2h
echo "[test] repo=$REPO_ROOT dry=$TRADER_DRY_RUN dur_sec=$DUR_SEC min_tradable=$MIN_TRADABLE_LINES"

# ---- STOP EVERYTHING ----
touch state/STOP 2>/dev/null || true
bash scripts/stop_all.sh 2>/dev/null || true
sleep 2
rm -f state/STOP 2>/dev/null || true
rm -f state/h24_watchdog.lock 2>/dev/null || true

# ---- RESET RUNTIME FILTERS ----
: > state/skip_mints_trader.txt
rm -f state/rl_skip_mints.json 2>/dev/null || true

# ---- Optional: if tradable too small but lastgood exists, restore now ----
if [ -s state/ready_scored_tradable.lastgood.jsonl ]; then
  TL="$(wc -l < state/ready_scored_tradable.jsonl 2>/dev/null || echo 0)"
  LG="$(wc -l < state/ready_scored_tradable.lastgood.jsonl 2>/dev/null || echo 0)"
  if [ "$TL" -lt "$MIN_TRADABLE_LINES" ] && [ "$LG" -gt 0 ]; then
    cp -a state/ready_scored_tradable.lastgood.jsonl state/ready_scored_tradable.jsonl
    echo "[test] restored tradable from lastgood: $LG lines (was $TL)"
  fi
fi

# ---- START WATCHDOG ----
: > state/watchdog.out
nohup bash -lc "cd '$REPO_ROOT' && bash scripts/h24_watchdog.sh" > state/watchdog.out 2>&1 &
WD_PID=$!
echo "[test] WATCHDOG pid=$WD_PID"

sleep 2
tail -n 40 state/watchdog.out || true

# ---- RUN FOR 2H ----
echo "[test] running for ${DUR_SEC}s..."
sleep "$DUR_SEC"

# ---- STOP CLEANLY ----
echo "[test] stopping..."
touch state/STOP 2>/dev/null || true
bash scripts/stop_all.sh 2>/dev/null || true
sleep 2
rm -f state/STOP 2>/dev/null || true

echo "[test] done."
echo "[test] last h24 log:"
ls -1t state/h24_*.log 2>/dev/null | head -n 1 || true
