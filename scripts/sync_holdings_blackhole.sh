#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
export PATH="$PWD/.venv/bin:$PATH"

MIN_UI="${MIN_UI:-0.000001}"
TMP_JSON="/tmp/token_accounts_sync.json"
OUT_FILE="state/skip_mints_trader.blackhole.txt"

spl-token accounts --output json > "$TMP_JSON"

python - <<PY
import json
from pathlib import Path

MIN_UI = float("${MIN_UI}")
p = Path("${TMP_JSON}")
j = json.load(open(p))

rows = []
def walk(x):
    if isinstance(x, dict):
        if "mint" in x and ("uiAmount" in x or "tokenAmount" in x):
            mint = x.get("mint")
            ta = x.get("address") or x.get("pubkey") or x.get("tokenAccount") or x.get("account")
            amt = None
            if "uiAmount" in x:
                amt = x["uiAmount"]
            elif isinstance(x.get("tokenAmount"), dict):
                amt = x["tokenAmount"].get("uiAmount")
            rows.append((mint, ta, amt))
        for v in x.values():
            walk(v)
    elif isinstance(x, list):
        for v in x:
            walk(v)

walk(j)

base_exclude = {
    "So11111111111111111111111111111111111111112",  # WSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}

mints = set()
for mint, ta, amt in rows:
    try:
        ui = float(amt)
    except Exception:
        continue
    if ui > MIN_UI and mint not in base_exclude:
        mints.add(mint)

out = Path("${OUT_FILE}")
out.write_text("".join(m + "\\n" for m in sorted(mints)), encoding="utf-8")

print(f"WROTE {out} mints={len(mints)} min_ui={MIN_UI}")
PY

sort -u -o "$OUT_FILE" "$OUT_FILE"
wc -l "$OUT_FILE"
echo "TOP 20 blackhole:"
head -n 20 "$OUT_FILE" || true
