#!/usr/bin/env bash
set -euo pipefail
cd /home/tng25/lino_FINAL_20260203_182626

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

export RLSKIP_RESYNC_EVERY_S="${RLSKIP_RESYNC_EVERY_S:-300}"

pkill -f "src/run_live.py|src/brain/brain_loop.py" 2>/dev/null || true

echo "[RL] initial sync+clean -> $RL_SKIP_FILE"
./.venv/bin/python scripts/rlskip_sync_from_brain.py || true
./.venv/bin/python scripts/rlskip_clean.py || true

echo "[RUN] starting full_with_brain_external_ready_v1.sh in background"
bash scripts/full_with_brain_external_ready_v1.sh &
RUNPID=$!

echo "[RL] resync loop every ${RLSKIP_RESYNC_EVERY_S}s (pid=$RUNPID)"
while kill -0 "$RUNPID" 2>/dev/null; do
  sleep "$RLSKIP_RESYNC_EVERY_S" || true
  if kill -0 "$RUNPID" 2>/dev/null; then
    echo "[RL] resync..."
    ./.venv/bin/python scripts/rlskip_sync_from_brain.py || true
    ./.venv/bin/python scripts/rlskip_clean.py || true
  fi
done

wait "$RUNPID" || true
