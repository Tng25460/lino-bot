#!/usr/bin/env bash
set -euo pipefail
cd /home/tng25/lino_FINAL_20260203_182626 || exit 1
source .venv/bin/activate || exit 1

export BRAIN_DB="state/brain.sqlite"
export READY_FILE="state/ready_tradable.jsonl"
export READY_SCORED_OUT="state/ready_scored.jsonl"

export BRAIN_OBS_MAX_MINTS="${BRAIN_OBS_MAX_MINTS:-30}"
export BRAIN_OBS_SLEEP_S="${BRAIN_OBS_SLEEP_S:-3.5}"

export BRAIN_MAX_IMPACT_PCT="${BRAIN_MAX_IMPACT_PCT:-0.12}"
export BRAIN_MAX_ROUTE_LEN="${BRAIN_MAX_ROUTE_LEN:-2}"

export READY_MIN_SCORE="${READY_MIN_SCORE:-0.2}"

while true; do
  date
  python -u scripts/brain_observe_ready.py 2>&1 | tee -a state/brain_observe_loop.log
  python -u scripts/brain_score_v1.py      2>&1 | tee -a state/brain_score_v1_loop.log
  python -u scripts/brain_export_ready_scored.py 2>&1 | tee -a state/brain_export_loop.log
  sqlite3 state/brain.sqlite 'select count(*) obs from token_observations; select count(*) scores from token_scores_v1;'
  echo "sleep 180s..."
  sleep 180
done
