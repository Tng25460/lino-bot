#!/usr/bin/env bash
set -u
cd ~/lino || exit 0
source .venv/bin/activate

# SCOUT profile (pump.fun / microcaps)
export SELL_PROFILE="SCOUT"
export SL_PCT="${SL_PCT:-0.18}"
export TP1_PCT="${TP1_PCT:-0.30}"
export TP2_PCT="${TP2_PCT:-1.00}"
export TP1_SELL_FRAC="${TP1_SELL_FRAC:-0.60}"
export TP2_SELL_FRAC="${TP2_SELL_FRAC:-0.25}"
export TRAIL_PCT="${TRAIL_PCT:-0.30}"
export TIME_STOP_S="${TIME_STOP_S:-1800}"

# scout sizing (petit)
export BUY_AMOUNT_SOL="${BUY_AMOUNT_SOL:-0.0015}"

PYTHONUNBUFFERED=1 python -u src/run_live.py
