#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PATH="$PWD/.venv/bin:$PATH"

mkdir -p state logs

ENV_FILE="${ENV_FILE:-state/live.env}"
READY_FILE_DEFAULT="state/READY_CANONICAL.jsonl"
SKIP_MINTS_FILE_DEFAULT="state/skip_mints_scan.txt"
TRADER_SKIP_MINTS_FILE_DEFAULT="state/skip_mints_trader.merged.txt"
LOCK_FILE="state/run_live.lock"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

export AUTO_BLACKHOLE_HOLDINGS=0
export AUTO_BUILD_HOLDINGS_SKIP="${AUTO_BUILD_HOLDINGS_SKIP:-1}"
export READY_FILE="${READY_FILE:-$READY_FILE_DEFAULT}"
export SKIP_MINTS_FILE="${SKIP_MINTS_FILE:-$SKIP_MINTS_FILE_DEFAULT}"
export TRADER_SKIP_MINTS_FILE="${TRADER_SKIP_MINTS_FILE:-$TRADER_SKIP_MINTS_FILE_DEFAULT}"
export TRADER_AUTOSKIP_FILE="${TRADER_AUTOSKIP_FILE:-state/skip_mints_trader.txt}"

[[ -f state/skip_mints_scan.txt ]] || : > state/skip_mints_scan.txt
[[ -f state/skip_mints_trader.txt ]] || : > state/skip_mints_trader.txt
[[ -f state/skip_mints_trader.blackhole.txt ]] || : > state/skip_mints_trader.blackhole.txt
[[ -f state/rl_skip_mints.json ]] || printf '{}' > state/rl_skip_mints.json

if [[ "${AUTO_BUILD_HOLDINGS_SKIP:-1}" = "1" ]] && [[ -x scripts/build_trader_skip_merged.sh ]]; then
  bash scripts/build_trader_skip_merged.sh \
    "state/skip_mints_trader.blackhole.txt" \
    "state/skip_mints_trader.merged.txt" \
    "state/skip_mints_trader.txt" \
    "state/skip_mints_scan.txt" || true
fi

if pgrep -f "src/run_live.py" >/dev/null 2>&1; then
  echo "[FATAL] run_live already running"
  pgrep -af "src/run_live.py" || true
  exit 1
fi

if [[ -f "$LOCK_FILE" ]]; then
  OLD_PID="$(cat "$LOCK_FILE" 2>/dev/null || true)"
  if [[ -n "${OLD_PID:-}" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "[FATAL] active lock pid=$OLD_PID"
    exit 1
  fi
  rm -f "$LOCK_FILE" || true
fi

echo $$ > "$LOCK_FILE"
cleanup() { rm -f "$LOCK_FILE" || true; }
trap cleanup EXIT INT TERM

TS="$(date +%Y%m%d_%H%M%S)"
LOG="logs/run_live_${TS}.log"

echo "▶️ START run_live @ ${TS} READY_FILE=${READY_FILE} SKIP_MINTS_FILE=${SKIP_MINTS_FILE} TRADER_SKIP_MINTS_FILE=${TRADER_SKIP_MINTS_FILE}"
echo "🧯 SIGUSR1 enabled: kill -USR1 <pid> to dump stack"

PYTHONUNBUFFERED=1 python -u src/run_live.py 2>&1 | tee -a "$LOG"
RC="${PIPESTATUS[0]}"
echo "run_live exit rc=$RC"
exit "$RC"
