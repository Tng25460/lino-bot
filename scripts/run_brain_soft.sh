#!/usr/bin/env bash
set -euo pipefail
cd /home/tng25/lino_FINAL_20260203_182626 || exit 1
source .venv/bin/activate || exit 1
source scripts/env_perf.sh

# brain: plus lent
export JUP_MIN_QUOTE_INTERVAL_S="${JUP_MIN_QUOTE_INTERVAL_S_BRAIN:-5.0}"
export JUP_MIN_QUOTE_INTERVAL_MIN_S="${JUP_MIN_QUOTE_INTERVAL_MIN_S_BRAIN:-4.0}"
export JUP_MIN_QUOTE_INTERVAL_MAX_S="${JUP_MIN_QUOTE_INTERVAL_MAX_S_BRAIN:-12.0}"

python -u scripts/brain_observe_ready.py
