#!/usr/bin/env bash
set -euo pipefail

cd /home/tng25/lino_FINAL_20260203_182626
source .venv/bin/activate

mkdir -p state

echo "🚀 FULL LIVE WITH BRAIN"

# Brain refresh loop (anti-double via flock inside script)
nohup bash -lc './scripts/brain_refresh_loop.sh' > state/brain_refresh_loop.log 2>&1 &

sleep 1
echo "brain_refresh_loop pid(s):"
pgrep -af "scripts/brain_refresh_loop.sh" || true

# IMPORTANT: trader lit le fichier scoré/filtré produit par le brain_refresh_loop
export READY_FILE="state/ready_scored_tradable.jsonl"

# Run live (BUY+SELL)
python -u src/run_live.py
