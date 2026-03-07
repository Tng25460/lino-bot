#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
export PATH="$PWD/.venv/bin:$PATH"

echo "==> stop total"
pkill -9 -f "src/run_live.py|watchdog_supervisor|run_live_guarded.sh|run_ready_pipeline|build_ready_canonical" || true
rm -f state/run_live.lock || true

echo "==> reset runtime"
printf '{}' > state/rl_skip_mints.json

echo "==> rebuild blacklist holdings"
bash scripts/sync_holdings_blackhole.sh

echo "==> rebuild READY"
bash scripts/run_ready_pipeline.sh
bash scripts/build_ready_canonical.sh

echo "==> relance"
bash scripts/run_live_guarded.sh

sleep 3
bash scripts/check_runtime_now.sh || true
