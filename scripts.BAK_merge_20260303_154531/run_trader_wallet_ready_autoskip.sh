#!/usr/bin/env bash
set -euo pipefail

READY_FILE="${1:?usage: $0 <ready_file.jsonl>}"
MAX_TRIES="${AUTO_SKIP_MAX_TRIES:-8}"
SKIP_FILE="${SKIP_MINTS_RUNTIME_FILE:-state/skip_mints_runtime.txt}"

touch "$SKIP_FILE"

echo "[RUN] READY_FILE=$READY_FILE"
echo "[RUN] SKIP_FILE=$SKIP_FILE MAX_TRIES=$MAX_TRIES"

# Ensure trader_exec sees the ready file + skip file
export READY_FILE="$READY_FILE"
export SKIP_MINTS_FILE="${SKIP_MINTS_FILE:-$SKIP_FILE}"

for i in $(seq 1 "$MAX_TRIES"); do
  echo
  echo "[AUTO] try $i/$MAX_TRIES …"

  # capture output
  TMP="$(mktemp -p state trader_autoskip.XXXXXX.log)"
  set +e
  PYTHONUNBUFFERED=1 scripts/run_trader_wallet_ready.sh "$READY_FILE" >"$TMP" 2>&1
    rc=$?
    echo "[AUTO] runner finished rc=$rc (check TMP for success/skip)"

  rc=$?
  set -e

  # show tail for context
  tail -n 120 "$TMP" || true

  # extract last picked mint
  pick="$(grep -Eo 'pick=\s*[A-Za-z0-9]{32,48}' "$TMP" | tail -n 1 | awk '{print $2}')"
  hold="$(grep -Eo 'already holding mint=[A-Za-z0-9]{32,48}' "$TMP" | tail -n 1 | sed 's/.*mint=//')"

  # detect "no route"
  if grep -qiE 'could not find any route|no route|route not found' "$TMP"; then
    if [ -n "${pick:-}" ]; then
      echo "[AUTO] no-route -> skip mint=$pick"
      echo "$pick" >> "$SKIP_FILE"
    else
      echo "[AUTO] no-route but could not parse pick mint (check $TMP)"
    fi
    continue
  fi

  # detect "already holding" (treat as skip and continue)
  if grep -qiE 'already holding' "$TMP"; then
    m="${hold:-${pick:-}}"
    if [ -n "${m:-}" ]; then
      echo "[AUTO] already-holding -> skip mint=$m"
      echo "$m" >> "$SKIP_FILE"
      continue
    fi
  fi

  # if success exit
  if [ "$rc" -eq 0 ]; then
    echo "[AUTO] success (rc=0) -> stop"
    exit 0
  fi

  # otherwise stop on unknown error
  echo "[AUTO] stop (rc=$rc) unknown error (see $TMP)"
  exit "$rc"
done

echo "[AUTO] max tries reached ($MAX_TRIES) -> stop"
exit 2
