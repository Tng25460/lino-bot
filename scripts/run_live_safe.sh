#!/usr/bin/env bash
set -u
cd ~/lino || exit 0
source .venv/bin/activate

# SAFE profile
export SELL_PROFILE="SAFE"
export SL_PCT="${SL_PCT:-0.12}"
export TP1_PCT="${TP1_PCT:-0.18}"
export TP2_PCT="${TP2_PCT:-0.40}"
export TP1_SELL_FRAC="${TP1_SELL_FRAC:-0.50}"
export TP2_SELL_FRAC="${TP2_SELL_FRAC:-0.25}"
export TRAIL_PCT="${TRAIL_PCT:-0.20}"
export TIME_STOP_S="${TIME_STOP_S:-3600}"

# buy sizing
export BUY_AMOUNT_SOL="${BUY_AMOUNT_SOL:-0.003}"

PYTHONUNBUFFERED=1 python -u src/run_live.py
