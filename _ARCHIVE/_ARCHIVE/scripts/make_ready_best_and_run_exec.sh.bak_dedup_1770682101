#!/usr/bin/env bash
set -euo pipefail

cd /home/tng25/lino_FINAL_20260203_182626 || exit 1
source .venv/bin/activate || exit 1

ts() { date "+%F %T"; }

# --- defaults (override by env) ---
: "${BRAIN_DB:=state/brain.sqlite}"
: "${READY_SCORED_IN:=state/ready_scored.jsonl}"
: "${READY_BEST_OUT:=state/ready_best.jsonl}"
: "${READY_SCORE_KEY:=brain_score_v1}"
: "${READY_MIN_SCORE:=0.2}"
: "${READY_TOPN:=5}"
: "${READY_PICK_MODE:=random_topn}"   # top1 | random_topn

: "${TRADER_DRY_RUN:=1}"
: "${BUY_AMOUNT_SOL:=0.003}"
: "${BUY_AMOUNT_LAMPORTS:=3000000}"

: "${JUP_BASE_URL:=https://lite-api.jup.ag}"
: "${RPC_HTTP:=https://api.mainnet-beta.solana.com}"

: "${KEYPAIR:=/home/tng25/lino_FINAL_20260203_182626/keypair.json}"

LOGDIR="${LOGDIR:-state}"
OUT_LOG="${OUT_LOG:-$LOGDIR/trader_exec_best_$(date +%s).log}"

mkdir -p "$LOGDIR"

echo "[$(ts)] [wrapper] start"
echo "  BRAIN_DB=$BRAIN_DB"
echo "  READY_SCORED_IN=$READY_SCORED_IN"
echo "  READY_BEST_OUT=$READY_BEST_OUT"
echo "  READY_SCORE_KEY=$READY_SCORE_KEY"
echo "  READY_MIN_SCORE=$READY_MIN_SCORE READY_TOPN=$READY_TOPN READY_PICK_MODE=$READY_PICK_MODE"
echo "  TRADER_DRY_RUN=$TRADER_DRY_RUN BUY_AMOUNT_SOL=$BUY_AMOUNT_SOL BUY_AMOUNT_LAMPORTS=$BUY_AMOUNT_LAMPORTS"
echo "  JUP_BASE_URL=$JUP_BASE_URL"
echo "  RPC_HTTP=$RPC_HTTP"
echo "  KEYPAIR=$KEYPAIR"
echo "  OUT_LOG=$OUT_LOG"

# --- sanity checks ---
test -f "$KEYPAIR" || { echo "❌ missing KEYPAIR=$KEYPAIR" >&2; exit 2; }
test -f "$READY_SCORED_IN" || { echo "❌ missing READY_SCORED_IN=$READY_SCORED_IN" >&2; exit 3; }
test -s "$READY_SCORED_IN" || { echo "❌ empty READY_SCORED_IN=$READY_SCORED_IN" >&2; exit 4; }

# --- reset env parasites that can break exporter/executor ---
unset READY_FILE READY_INP READY_SCORED_OUT READY_SCORE_TTL_S 2>/dev/null || true

# --- wallet pubkey env (trader_exec expects these) ---
PUB="$(solana-keygen pubkey "$KEYPAIR")"
export WALLET_PUBKEY="$PUB"
export TRADER_USER_PUBLIC_KEY="$PUB"

# --- export core env for trader_exec ---
export TRADER_DRY_RUN BUY_AMOUNT_SOL BUY_AMOUNT_LAMPORTS JUP_BASE_URL RPC_HTTP

# --- choose best mint from scored ---
export READY_SCORED_IN READY_BEST_OUT READY_SCORE_KEY READY_MIN_SCORE READY_TOPN READY_PICK_MODE READY_BEST_OUT

python -u scripts/ready_best_from_scored.py

if [[ ! -s "$READY_BEST_OUT" ]]; then
  echo "❌ READY_BEST_OUT produced empty file: $READY_BEST_OUT" >&2
  echo "   tip: lower READY_MIN_SCORE or increase READY_TOPN" >&2
  exit 5
fi

echo "[$(ts)] [wrapper] ready_best:"
head -n 1 "$READY_BEST_OUT" || true

# --- run trader_exec on the single best mint ---
export READY_FILE="$READY_BEST_OUT"

echo "[$(ts)] [wrapper] running trader_exec..."
python -u src/trader_exec.py 2>&1 | tee "$OUT_LOG"

echo "[$(ts)] [wrapper] summary (grep):"
grep -aE "pick=|amount_lamports=|built tx|quote failed http=|⛔ STRICT_ONLY|ROUTE_GATE|🧊 RL_SKIP" -n "$OUT_LOG" | tail -n 120 || true

echo "[$(ts)] [wrapper] done"
