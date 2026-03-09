#!/usr/bin/env bash
set -euo pipefail

OUT="state/READY_CANONICAL.jsonl"
TMP="$(mktemp)"

echo "[READY] build canonical (SMART DEDUP: prefer enriched)"

# 1) concat univers large
cat \
  state/ready_scored_tradable.jsonl \
  state/ready_wide.noheld.jsonl \
  state/ready_wide.noheld.tradable.jsonl \
  state/ready_enriched.jsonl \
  state/ready_final.jsonl \
  state/universe_600.jsonl \
  state/recover_wallet_picked.jsonl \
  state/route_rejects_scored_any.jsonl \
  state/route_rejects_scored_strict.jsonl \
  2>/dev/null \
| grep -v '^[[:space:]]*$' \
> "$TMP"

# 2) smart dedup: garder la ligne la plus "riche" par mint
TMP_FILE="$TMP" OUT_FILE="$OUT" python - << 'PY'
import os, json
from pathlib import Path

tmp = Path(os.environ["TMP_FILE"])
out = Path(os.environ["OUT_FILE"])

best = {}  # mint -> (score, obj)

WEIGHTS = {
    "volume_5m_usd": 50,
    "tx_5m": 40,
    "liquidity_usd": 30,
    "profile": 25,
    "top1_pct": 10,
    "top5_pct": 10,
    "brain_score": 5,
    "brain_score_flow": 2,
    "brain_score_market": 2,
    "brain_score_history": 2,
    "mint": 1,
}

def richness(o: dict) -> int:
    s = 0
    for k, w in WEIGHTS.items():
        if k in o and o.get(k) not in (None, "", 0, 0.0, {}, []):
            s += w
    if isinstance(o.get("profile"), dict) and len(o["profile"]) > 0:
        s += 15
    return s

bad = 0
total = 0

for line in tmp.read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if not line:
        continue
    total += 1
    try:
        o = json.loads(line)
    except Exception:
        bad += 1
        continue

    mint = o.get("mint") or o.get("outputMint") or o.get("address")
    if not mint:
        continue

    sc = richness(o)
    prev = best.get(mint)
    if prev is None or sc > prev[0]:
        best[mint] = (sc, o)

lines = [json.dumps(v[1], ensure_ascii=False) for v in best.values()]
out.write_text("\n".join(lines) + "\n", encoding="utf-8")

print(f"[READY] tmp_lines={total} bad_json={bad} unique_mints={len(lines)} -> {out}")
PY

rm -f "$TMP"
echo "[READY] canonical_lines=$(wc -l < "$OUT")"
