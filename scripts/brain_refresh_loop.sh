#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/tng25/lino_FINAL_20260203_182626}"
cd "$REPO_ROOT"
source .venv/bin/activate

SLEEP_SEC="${SLEEP_SEC:-120}"
MIN_TRADABLE_LINES="${MIN_TRADABLE_LINES:-10}"

BRAIN_SCORE_MIN="${BRAIN_SCORE_MIN:-0.03}"
BRAIN_TOPN="${BRAIN_TOPN:-60}"

FILTER_TRADABLE_MIN_INTERVAL_SEC="${FILTER_TRADABLE_MIN_INTERVAL_SEC:-3.0}"  # 3s between quote calls to respect Jupiter rate limits
FILTER_TRADABLE_RETRIES="${FILTER_TRADABLE_RETRIES:-10}"
FILTER_TRADABLE_ON429_KEEP="${FILTER_TRADABLE_ON429_KEEP:-1}"
FILTER_TRADABLE_AMOUNT="${FILTER_TRADABLE_AMOUNT:-10000000}"
FILTER_TRADABLE_SLIP_BPS="${FILTER_TRADABLE_SLIP_BPS:-120}"
FILTER_TRADABLE_MAX_NEG_PNL_PCT="${FILTER_TRADABLE_MAX_NEG_PNL_PCT:-5}"

TRADABLE_OUT="state/ready_scored_tradable.jsonl"
LASTGOOD="state/ready_scored_tradable.lastgood.jsonl"

mkdir -p state

while true; do
  echo "[brain_refresh] cycle start $(date -Is)" | tee -a state/brain_refresh_loop.log

  # 1) brain -> state/ready_scored.jsonl
  python -u src/brain/brain_loop.py >> state/brain_loop.log 2>&1 || true

  # 2) tradable filter -> atomic write via tmp file
  _tmp_out="${TRADABLE_OUT}.tmp.$$"
  # Ensure tmp file is cleaned up even on interrupt
  trap 'rm -f "$_tmp_out"' EXIT INT TERM
  BRAIN_SCORE_MIN="$BRAIN_SCORE_MIN" \
  BRAIN_TOPN="$BRAIN_TOPN" \
  FILTER_TRADABLE_MIN_INTERVAL_SEC="$FILTER_TRADABLE_MIN_INTERVAL_SEC" \
  FILTER_TRADABLE_RETRIES="$FILTER_TRADABLE_RETRIES" \
  FILTER_TRADABLE_ON429_KEEP="$FILTER_TRADABLE_ON429_KEEP" \
  FILTER_TRADABLE_AMOUNT="$FILTER_TRADABLE_AMOUNT" \
  FILTER_TRADABLE_SLIP_BPS="$FILTER_TRADABLE_SLIP_BPS" \
  FILTER_TRADABLE_MAX_NEG_PNL_PCT="$FILTER_TRADABLE_MAX_NEG_PNL_PCT" \
  MIN_TRADABLE_LINES="$MIN_TRADABLE_LINES" \
  FILTER_TRADABLE_LASTGOOD="$LASTGOOD" \
  python -u scripts/filter_ready_tradable.py \
    --in  state/ready_scored.jsonl \
    --out "$_tmp_out" \
    >> state/brain_refresh_loop.log 2>&1 || true

  # Atomic replace: only update if tmp file is non-empty
  if [ -s "$_tmp_out" ]; then
    mv "$_tmp_out" "$TRADABLE_OUT"
  else
    rm -f "$_tmp_out"
    echo "[brain_refresh] filter produced empty output, keeping previous" | tee -a state/brain_refresh_loop.log
  fi

  # 3) count lines in tradable output
  _lines=0
  if [ -s "$TRADABLE_OUT" ]; then
    _lines=$(wc -l < "$TRADABLE_OUT" 2>/dev/null || echo 0)
  fi

  # 4) fallback: if tradable too small, use lastgood or ready_scored
  if [ "$_lines" -lt "$MIN_TRADABLE_LINES" ]; then
    echo "[brain_refresh] tradable lines=$_lines < MIN_TRADABLE_LINES=$MIN_TRADABLE_LINES" | tee -a state/brain_refresh_loop.log
    if [ -s "$LASTGOOD" ]; then
      _lg_lines=$(wc -l < "$LASTGOOD" 2>/dev/null || echo 0)
      echo "[brain_refresh] using lastgood lines=$_lg_lines -> $TRADABLE_OUT" | tee -a state/brain_refresh_loop.log
      cp "$LASTGOOD" "$TRADABLE_OUT"
      _lines=$_lg_lines
    elif [ -s "state/ready_scored.jsonl" ]; then
      echo "[brain_refresh] lastgood missing -> fallback ready_scored.jsonl -> $TRADABLE_OUT" | tee -a state/brain_refresh_loop.log
      cp "state/ready_scored.jsonl" "$TRADABLE_OUT"
      _lines=$(wc -l < "$TRADABLE_OUT" 2>/dev/null || echo 0)
    fi
  fi

  echo "[brain_refresh] cycle done tradable_lines=$_lines sleep=$SLEEP_SEC" | tee -a state/brain_refresh_loop.log
  sleep "$SLEEP_SEC"
done
