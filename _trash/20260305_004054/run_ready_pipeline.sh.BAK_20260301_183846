#!/usr/bin/env bash
set -euo pipefail

IN="state/ready_scored_tradable.jsonl"
MID="state/ready_enriched.jsonl"
OUT="state/ready_final.jsonl"

: > "$MID"
: > "$OUT"

while IFS= read -r line; do
  [ -z "$line" ] && continue

  echo "$line" \
    | python scripts/enrich_stub.py \
    >> "$MID"

done < "$IN"

bash scripts/filter_tradable.sh
