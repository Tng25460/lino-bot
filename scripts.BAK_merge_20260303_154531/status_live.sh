#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== lock ==="
ls -l state/run_live.lock 2>/dev/null || true

echo "=== watchdog heartbeat (unix ts) ==="
cat state/watchdog_heartbeat.txt 2>/dev/null || echo "no heartbeat"

echo "=== last logs ==="
ls -1t logs/run_live_*.log 2>/dev/null | head -n 5 || true
