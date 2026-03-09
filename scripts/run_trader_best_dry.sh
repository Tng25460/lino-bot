#!/usr/bin/env bash
set -euo pipefail
cd /home/tng25/lino_FINAL_20260203_182626 || exit 1
source .venv/bin/activate || exit 1

PUB="$(solana-keygen pubkey /home/tng25/lino_FINAL_20260203_182626/keypair.json)"
export WALLET_PUBKEY="$PUB"
export TRADER_USER_PUBLIC_KEY="$PUB"

export TRADER_DRY_RUN="${TRADER_DRY_RUN:-1}"
export BUY_AMOUNT_SOL="${BUY_AMOUNT_SOL:-0.003}"
export BUY_AMOUNT_LAMPORTS="${BUY_AMOUNT_LAMPORTS:-3000000}"

export JUP_BASE_URL="${JUP_BASE_URL:-https://lite-api.jup.ag}"
export RPC_HTTP="${RPC_HTTP:-https://api.mainnet-beta.solana.com}"

# Use scored file produced by brain export
export READY_SCORED_IN="${READY_SCORED_IN:-state/ready_scored.jsonl}"
export READY_BEST_OUT="${READY_BEST_OUT:-state/ready_best.jsonl}"
export READY_SCORE_KEY="${READY_SCORE_KEY:-brain_score_v1}"
export READY_MIN_SCORE="${READY_MIN_SCORE:-0.2}"
export READY_TOPN="${READY_TOPN:-5}"
export READY_PICK_MODE="${READY_PICK_MODE:-random_topn}"

python -u scripts/ready_best_from_scored.py
export READY_FILE="$READY_BEST_OUT"

python -u src/trader_exec.py 2>&1 | tee state/trader_exec_best_dry.log
grep -aE "pick=|amount_lamports=|built tx|quote failed http=|🧊 RL_SKIP" -n state/trader_exec_best_dry.log | tail -n 120
