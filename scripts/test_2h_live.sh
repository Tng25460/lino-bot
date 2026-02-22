#!/usr/bin/env bash
# 2-hour DRY_RUN smoke test: verifies the bot pipeline runs without crashes.
# Runs trader_exec ONE_SHOT DRY_RUN for multiple iterations and reports outcome.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/tng25/lino_FINAL_20260203_182626}"
cd "$REPO_ROOT"
source .venv/bin/activate

DURATION_SEC="${TEST_DURATION_SEC:-7200}"  # 2 hours default
LOOP_SLEEP="${TEST_LOOP_SLEEP:-60}"
LOG="state/test_2h_$(date +%Y%m%d_%H%M%S).log"

mkdir -p state

echo "[test_2h] Starting 2h DRY_RUN smoke test (duration=${DURATION_SEC}s loop_sleep=${LOOP_SLEEP}s)" | tee -a "$LOG"
echo "[test_2h] Log: $LOG"
echo "[test_2h] Create state/STOP to abort early"

_start=$(date +%s)
_iter=0
_buy_count=0
_skip_count=0
_err_count=0

export TRADER_DRY_RUN=1
export ONE_SHOT=1
export CANDIDATE_TRIES="${CANDIDATE_TRIES:-10}"

while true; do
  _now=$(date +%s)
  _elapsed=$(( _now - _start ))
  if [ "$_elapsed" -ge "$DURATION_SEC" ]; then
    echo "[test_2h] Duration reached (${_elapsed}s >= ${DURATION_SEC}s)" | tee -a "$LOG"
    break
  fi
  if [ -f "state/STOP" ]; then
    echo "[test_2h] STOP file detected -> aborting" | tee -a "$LOG"
    break
  fi

  _iter=$(( _iter + 1 ))
  echo "[test_2h] iter=$_iter elapsed=${_elapsed}s" | tee -a "$LOG"

  _out=$(TRADER_DRY_RUN=1 ONE_SHOT=1 python -u src/trader_exec.py 2>&1 || true)
  echo "$_out" >> "$LOG"

  if echo "$_out" | grep -q "sent txsig=\|built tx ->"; then
    _buy_count=$(( _buy_count + 1 ))
    echo "[test_2h] iter=$_iter -> BUY/BUILD detected" | tee -a "$LOG"
  elif echo "$_out" | grep -q "NO_BUY after tries=\|no candidates\|ready_to_trade vide"; then
    _skip_count=$(( _skip_count + 1 ))
    echo "[test_2h] iter=$_iter -> no candidates (skip)" | tee -a "$LOG"
  elif echo "$_out" | grep -q "❌\|exception\|Traceback"; then
    _err_count=$(( _err_count + 1 ))
    echo "[test_2h] iter=$_iter -> ERROR detected" | tee -a "$LOG"
  else
    echo "[test_2h] iter=$_iter -> other (soft skip)" | tee -a "$LOG"
  fi

  sleep "$LOOP_SLEEP"
done

echo "[test_2h] SUMMARY: iters=$_iter buys=$_buy_count skips=$_skip_count errors=$_err_count" | tee -a "$LOG"
if [ "$_err_count" -gt 0 ]; then
  echo "[test_2h] ⚠️  ERRORS detected - check $LOG" | tee -a "$LOG"
  exit 1
else
  echo "[test_2h] ✅ Test passed - no errors" | tee -a "$LOG"
  exit 0
fi
