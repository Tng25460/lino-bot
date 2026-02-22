#!/usr/bin/env bash
# Start bot H24 in a tmux session with watchdog (no duplicates)
# Usage: bash scripts/start_h24.sh
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/tng25/lino_FINAL_20260203_182626}"
SESSION="lino"

cd "$REPO_ROOT"

# Guard: do not start if session already exists
if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "⚠️  tmux session '$SESSION' already running. Use 'tmux attach -t $SESSION' to view."
  echo "   To restart: bash scripts/stop_all.sh && bash scripts/start_h24.sh"
  exit 0
fi

echo "🚀 Starting lino-bot H24 in tmux session '$SESSION'"

# Create tmux session with watchdog in window 0
tmux new-session -d -s "$SESSION" -n watchdog \
  "REPO_ROOT=$REPO_ROOT bash $REPO_ROOT/scripts/lino_watchdog.sh 2>&1 | tee -a $REPO_ROOT/state/watchdog.log"

echo "✅ Started. Commands:"
echo "   View:  tmux attach -t $SESSION"
echo "   Stop:  bash $REPO_ROOT/scripts/stop_all.sh"
echo "   Logs:  bash $REPO_ROOT/scripts/tail_live.sh"
