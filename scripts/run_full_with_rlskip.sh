#!/usr/bin/env bash
set -euo pipefail

cd /home/tng25/lino_FINAL_20260203_182626

pkill -f "src/run_live.py|src/brain/brain_loop.py" 2>/dev/null || true

export READY_FILE="${READY_FILE:-state/ready_tradable.jsonl}"



export READY_SCORED_FILE="${READY_SCORED_FILE:-state/ready_scored.jsonl}"
export SKIP_MINTS_FILE="${SKIP_MINTS_FILE:-state/skip_mints_trader.txt}"
export BRAIN_DB_PATH="${BRAIN_DB_PATH:-state/brain.sqlite}"
export RL_SKIP_FILE="${RL_SKIP_FILE:-state/rl_skip_mints.json}"

export HIST_SKIP_MIN_N="${HIST_SKIP_MIN_N:-1}"
export HIST_SKIP_AVG_PNL_MAX="${HIST_SKIP_AVG_PNL_MAX:--0.10}"
export HIST_SKIP_SEC="${HIST_SKIP_SEC:-3600}"
export HIST_SKIP_LIMIT="${HIST_SKIP_LIMIT:-200}"
export HIST_SKIP_MAX_AGE_S="${HIST_SKIP_MAX_AGE_S:-259200}"

echo "[RL] sync+clean -> $RL_SKIP_FILE"
./.venv/bin/python scripts/rlskip_sync_from_brain.py
./.venv/bin/python scripts/rlskip_clean.py
# --- REENTRY_HISTGOOD_V1 ---
# Optional: merge top historical winners back into READY_FILE (re-entry bias)
if [ "${REENTRY_HISTGOOD:-0}" = "1" ]; then
  echo "[REENTRY] histgood enabled -> building ready_tradable_plus_histgood.jsonl"
  ./.venv/bin/python scripts/make_ready_plus_histgood.py || true
  if [ -s "state/ready_tradable_plus_histgood.jsonl" ]; then
    export READY_FILE="state/ready_tradable_plus_histgood.jsonl"
    echo "[REENTRY] READY_FILE switched -> ${READY_FILE}"
  else
    echo "[REENTRY] WARN: state/ready_tradable_plus_histgood.jsonl missing/empty (keep READY_FILE=${READY_FILE})"
  fi
fi
# --- /REENTRY_HISTGOOD_V1 ---


echo "[RUN] full_with_brain_external_ready_v1.sh"
exec bash scripts/full_with_brain_external_ready_v1.sh
