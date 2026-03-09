#!/usr/bin/env bash
set -euo pipefail
cd "${REPO_ROOT:-/home/tng25/lino_FINAL_20260203_182626}" || exit 1
source .venv/bin/activate || true

echo "=== 1) COMPILE CHECK ==="
python -m py_compile src/trader_exec.py src/trader_loop.py src/run_live.py src/brain/brain_loop.py

echo "=== 2) SHELL CHECK ==="
bash -n scripts/h24_watchdog.sh scripts/brain_refresh_loop.sh scripts/stop_all.sh scripts/full_live_with_brain.sh scripts/monitor_live.sh

echo "=== 3) STOP ALL (clean) ==="
touch state/STOP 2>/dev/null || true
bash scripts/stop_all.sh 2>/dev/null || true
sleep 2
rm -f state/STOP 2>/dev/null || true
rm -f state/h24_watchdog.lock 2>/dev/null || true

echo "=== 4) RESET runtime (skip/rlskip) ==="
: > state/skip_mints_trader.txt
rm -f state/rl_skip_mints.json 2>/dev/null || true

echo "=== 5) RESTORE lastgood tradable if present ==="
if [ -s state/ready_scored_tradable.lastgood.jsonl ]; then
  cp -a state/ready_scored_tradable.lastgood.jsonl state/ready_scored_tradable.jsonl
  echo "RESTORED: state/ready_scored_tradable.jsonl from lastgood"
fi
wc -l state/ready_scored_tradable.jsonl 2>/dev/null || true

echo "=== 6) RUN brain_refresh 1 cycle (background 15s) ==="
# Laisse tourner un peu puis stop
nohup bash -lc "cd $(pwd) && SLEEP_SEC=999999 ./scripts/brain_refresh_loop.sh" > state/brain_refresh_test.out 2>&1 &
BRPID=$!
sleep 15
kill "${BRPID}" 2>/dev/null || true
sleep 1
tail -n 120 state/brain_refresh_test.out || true
wc -l state/ready_scored.jsonl state/ready_scored_tradable.jsonl 2>/dev/null || true

echo "=== 7) ONE_SHOT DRY trader_exec sur tradable ==="
export TRADER_DRY_RUN=1
export ONE_SHOT=1
export READY_FILE="state/ready_scored_tradable.jsonl"
export DISABLE_HIST_BAD="${DISABLE_HIST_BAD:-1}"
export DISABLE_RL_SKIP="${DISABLE_RL_SKIP:-0}"
python -u src/trader_exec.py 2>&1 | tee /tmp/trader_exec_smoke.log || true
echo "--- markers ---"
grep -aE "ready_count=|pick=|NO_BUY|quote failed http= *429|built tx|sent txsig=|recorded BUY|Traceback|FATAL" -n /tmp/trader_exec_smoke.log | tail -n 120 || true

echo "=== OK test_full done ==="
