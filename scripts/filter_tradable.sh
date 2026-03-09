#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p state
set -euo pipefail

IN="state/ready_scored.filtered.jsonl"
OUT="state/ready_scored_tradable.jsonl"

: > "$OUT"

while IFS= read -r line; do
  [ -z "$line" ] && continue

  echo "$line" \
  | python scripts/anti_rug_check.py \
  | python scripts/liquidity_volume_filter.py \
    | python scripts/deny_nodata_ready.py \
  | python scripts/jup_tradable_guard.py \
    | python scripts/deny_tokenized_equities.py \
  >> "$OUT" || true

done < "$IN"
