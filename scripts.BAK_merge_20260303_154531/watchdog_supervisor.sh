#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

BASE_SLEEP="${BASE_SLEEP:-3}"
MAX_SLEEP="${MAX_SLEEP:-120}"
JITTER_MAX="${JITTER_MAX:-3}"
HEALTH_FILE="${HEALTH_FILE:-state/watchdog_heartbeat.txt}"

sleep_s="$BASE_SLEEP"

echo "🧿 WATCHDOG start @ $(date)"
while true; do
  date +%s > "$HEALTH_FILE" || true

  set +e
  bash scripts/run_live_guarded.sh
  rc=$?
  set -e

  # lock busy => on évite spam
  if [ "$rc" -eq 23 ]; then
    wait=$(( 30 + (RANDOM % 10) ))
    echo "🔒 run_live déjà actif -> sleep ${wait}s @ $(date)"
    sleep "$wait"
    continue
  fi

  if [ "$rc" -eq 0 ]; then
    sleep_s="$BASE_SLEEP"
  else
    sleep_s=$(( sleep_s * 2 ))
    [ "$sleep_s" -gt "$MAX_SLEEP" ] && sleep_s="$MAX_SLEEP"
  fi

  jitter=$(( RANDOM % (JITTER_MAX + 1) ))
  wait=$(( sleep_s + jitter ))
  echo "🔁 restart in ${wait}s (rc=$rc) @ $(date)"
  sleep "$wait"
done
