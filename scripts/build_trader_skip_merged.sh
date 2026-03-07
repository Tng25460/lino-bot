#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$PWD/.venv/bin:$PATH"

BLACKHOLE_FILE="${1:-state/skip_mints_trader.blackhole.txt}"
OUT_FILE="${2:-state/skip_mints_trader.merged.txt}"
AUTOSKIP_FILE="${3:-state/skip_mints_trader.txt}"
SCAN_FILE="${4:-state/skip_mints_scan.txt}"
TMP_JSON="/tmp/lino_token_accounts_$$.json"
TMP_HOLD="/tmp/lino_holdings_mints_$$.txt"
MIN_UI="${MIN_UI:-0.000001}"

mkdir -p state
[[ -f "$BLACKHOLE_FILE" ]] || : > "$BLACKHOLE_FILE"
[[ -f "$AUTOSKIP_FILE"  ]] || : > "$AUTOSKIP_FILE"
[[ -f "$SCAN_FILE"      ]] || : > "$SCAN_FILE"

: > "$TMP_HOLD"

if command -v spl-token >/dev/null 2>&1; then
  spl-token accounts --output json > "$TMP_JSON" 2>/dev/null || echo '{}' > "$TMP_JSON"
  python - <<PY
import json
from pathlib import Path
p = Path("$TMP_JSON")
try:
    j = json.loads(p.read_text())
except Exception:
    j = {}
rows = []
def walk(x):
    if isinstance(x, dict):
        if "mint" in x and ("uiAmount" in x or "tokenAmount" in x):
            mint = x.get("mint")
            amt = x.get("uiAmount")
            if amt is None and isinstance(x.get("tokenAmount"), dict):
                amt = x["tokenAmount"].get("uiAmount")
            rows.append((mint, amt))
        for v in x.values():
            walk(v)
    elif isinstance(x, list):
        for v in x:
            walk(v)
walk(j)
seen=set(); out=[]
for mint, amt in rows:
    try:
        ui=float(amt)
    except Exception:
        continue
    if mint and ui > float("$MIN_UI") and mint not in seen:
        seen.add(mint)
        out.append(mint)
Path("$TMP_HOLD").write_text("\n".join(sorted(out)) + ("\n" if out else ""))
print(f"HOLDINGS_MINTS={len(out)}")
PY
fi

cat "$BLACKHOLE_FILE" "$AUTOSKIP_FILE" "$SCAN_FILE" "$TMP_HOLD" 2>/dev/null \
  | sed '/^\s*$/d' \
  | sort -u > "$OUT_FILE"

echo "WROTE $OUT_FILE lines=$(wc -l < "$OUT_FILE")"
rm -f "$TMP_JSON" "$TMP_HOLD" || true
