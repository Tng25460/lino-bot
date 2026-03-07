#!/usr/bin/env bash
set -euo pipefail
cd /home/tng25/lino_FINAL_20260203_182626
source .venv/bin/activate

SLEEP_SEC="${SLEEP_SEC:-120}"

# Option C (réglages)
export BRAIN_SCORE_MIN="${BRAIN_SCORE_MIN:-0.15}"
export BRAIN_TOPN="${BRAIN_TOPN:-25}"
export FILTER_TRADABLE_MIN_INTERVAL_SEC="${FILTER_TRADABLE_MIN_INTERVAL_SEC:-0.25}"
export FILTER_TRADABLE_RETRIES="${FILTER_TRADABLE_RETRIES:-6}"
export FILTER_TRADABLE_ON429_KEEP="${FILTER_TRADABLE_ON429_KEEP:-1}"
export FILTER_TRADABLE_AMOUNT="${FILTER_TRADABLE_AMOUNT:-10000000}"
export FILTER_TRADABLE_SLIP_BPS="${FILTER_TRADABLE_SLIP_BPS:-120}"

mkdir -p state

while true; do
  # 1) brain_loop génère ready_scored.jsonl (et applique RL_SKIP)
  python -u src/brain/brain_loop.py >> state/brain_loop.log 2>&1 || true

  # 2) on garde seulement topN scorés + tradables
  python -u scripts/filter_ready_tradable.py \
    --in  state/ready_scored.jsonl \
    --out state/ready_scored_tradable.jsonl >> state/brain_loop.log 2>&1 || true

  sleep "$SLEEP_SEC"
done
