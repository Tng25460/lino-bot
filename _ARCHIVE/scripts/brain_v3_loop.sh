#!/usr/bin/env bash
set -e
cd /home/tng25/lino_FINAL_20260203_182626 || exit 1
source .venv/bin/activate || exit 1
while true; do
  python scripts/brain_v3_analyze.py || true
  python scripts/brain_v3_alloc.py   || true
  bash   scripts/brain_v3_apply_alloc.sh || true
  sleep 300
done
