#!/usr/bin/env bash
# Stop all lino-bot processes safely (no pkill/killall by name)
set -euo pipefail

echo "🛑 stop_all: terminating lino-bot processes"

# Kill by pattern using pgrep + kill (avoids killall/pkill)
for PATTERN in "brain_refresh_loop.sh" "brain_loop.py" "run_live.py" "trader_loop.py" "trader_exec.py" "filter_ready_tradable.py" "lino_watchdog.sh"; do
  PIDS=$(pgrep -f "$PATTERN" 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "  killing $PATTERN pids: $PIDS"
    for PID in $PIDS; do
      kill "$PID" 2>/dev/null || true
    done
  fi
done

# Kill tmux session if it exists
if command -v tmux >/dev/null 2>&1; then
  if tmux has-session -t lino 2>/dev/null; then
    echo "  killing tmux session: lino"
    tmux kill-session -t lino 2>/dev/null || true
  fi
fi

echo "✅ stop_all done"
