#!/usr/bin/env bash
# Tail live bot logs with useful grep filters
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/tng25/lino_FINAL_20260203_182626}"
cd "$REPO_ROOT" 2>/dev/null || true

LOG="${1:-state/run_live.nohup.log}"

if [ ! -f "$LOG" ]; then
  echo "⚠️  Log file not found: $LOG"
  echo "   Available logs:"
  ls state/*.log state/*.nohup.log 2>/dev/null || true
  exit 1
fi

echo "=== tailing $LOG (Ctrl+C to stop) ==="
tail -n 80 -f "$LOG" 2>/dev/null | grep -a \
  -e "BUY\|SELL\|PICK\|RC=\|EXEC_RC\|TRADER_EXEC_RC\|429\|RL_SKIP\|SKIP\|HOLD\|LOW_SOL\|PROFILE\|sent txsig\|ERROR\|❌\|✅\|⚠️\|🧊\|🛑\|🧪\|🔁\|💰\|🚀\|⏸️\|brain_refresh\|lastgood\|tradable_lines\|NO_BUY_BACKOFF" \
  || true
