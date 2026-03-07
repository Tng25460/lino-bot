#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="${REPO_ROOT:-/home/tng25/lino_FINAL_20260203_182626}"
cd "$REPO_ROOT" || exit 1

LOG="${LOG:-$(ls -1t state/h24_*.log 2>/dev/null | head -n 1)}"
if [ -z "${LOG:-}" ] || [ ! -f "$LOG" ]; then
  echo "NO h24 log found in state/ (start watchdog first)"
  ls -1t state/*.log 2>/dev/null | head || true
  exit 0
fi

echo "LOG=$LOG"
tail -f "$LOG" | grep -aE \
"ready_count=|pick=|NO_BUY|built tx|sent txsig=|recorded BUY|quote failed http= *429|RL_SKIP|HIST_BAD|already holding|autoskip|SELL_TICK|\[SELL\]|TP1|TP2|route_fail|INSUFFICIENT|Traceback|FATAL"
