#!/usr/bin/env bash
set -euo pipefail
cd /home/tng25/lino_FINAL_20260203_182626
source .venv/bin/activate

mkdir -p state
: > state/brain_loop.log
: > state/brain_refresh_loop.log
: > state/run_live.log

export READY_FILE="state/ready_scored_tradable.jsonl"

nohup bash -lc "./scripts/brain_refresh_loop.sh" > state/brain_refresh_loop.nohup.log 2>&1 &
echo $! > state/brain_refresh.pid
sleep 1

nohup bash -lc "python -u src/run_live.py" > state/run_live.nohup.log 2>&1 &
echo $! > state/run_live.pid

echo "OK started:"
echo "  brain_refresh pid=$(cat state/brain_refresh.pid)"
echo "  run_live     pid=$(cat state/run_live.pid)"
