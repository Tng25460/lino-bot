#!/usr/bin/env bash
set -euo pipefail

cd /home/tng25/lino_FINAL_20260203_182626
source .venv/bin/activate

SLEEP_SEC="${SLEEP_SEC:-120}"

BRAIN_SCORE_MIN="${BRAIN_SCORE_MIN:-0.03}"
BRAIN_TOPN="${BRAIN_TOPN:-60}"

FILTER_TRADABLE_MIN_INTERVAL_SEC="${FILTER_TRADABLE_MIN_INTERVAL_SEC:-0.7}"
FILTER_TRADABLE_RETRIES="${FILTER_TRADABLE_RETRIES:-10}"
FILTER_TRADABLE_ON429_KEEP="${FILTER_TRADABLE_ON429_KEEP:-1}"
FILTER_TRADABLE_AMOUNT="${FILTER_TRADABLE_AMOUNT:-10000000}"
FILTER_TRADABLE_SLIP_BPS="${FILTER_TRADABLE_SLIP_BPS:-120}"
FILTER_TRADABLE_MAX_NEG_PNL_PCT="${FILTER_TRADABLE_MAX_NEG_PNL_PCT:-5}"

mkdir -p state

while true; do
  echo "[brain_refresh] cycle start $(date -Is)" | tee -a state/brain_refresh_loop.log

  # 1) brain -> state/ready_scored.jsonl
  python -u src/brain/brain_loop.py >> state/brain_loop.log 2>&1 || true

  # 2) tradable -> state/ready_scored_tradable.jsonl
  BRAIN_SCORE_MIN="$BRAIN_SCORE_MIN" \
  BRAIN_TOPN="$BRAIN_TOPN" \
  FILTER_TRADABLE_MIN_INTERVAL_SEC="$FILTER_TRADABLE_MIN_INTERVAL_SEC" \
  FILTER_TRADABLE_RETRIES="$FILTER_TRADABLE_RETRIES" \
  FILTER_TRADABLE_ON429_KEEP="$FILTER_TRADABLE_ON429_KEEP" \
  FILTER_TRADABLE_AMOUNT="$FILTER_TRADABLE_AMOUNT" \
  FILTER_TRADABLE_SLIP_BPS="$FILTER_TRADABLE_SLIP_BPS" \
  FILTER_TRADABLE_MAX_NEG_PNL_PCT="$FILTER_TRADABLE_MAX_NEG_PNL_PCT" \
  python -u scripts/filter_ready_tradable.py \
    --in  state/ready_scored.jsonl \
    --out state/ready_scored_tradable.jsonl \
    >> state/brain_refresh_loop.log 2>&1 || true

  sleep "$SLEEP_SEC"
done
