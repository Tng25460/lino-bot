import json, math, re
from pathlib import Path

PATH = Path("state/READY_CANONICAL.jsonl")

# patterns "stock-like" (actions / indices / commodities). Ajuste si tu veux.
STOCKLIKE = re.compile(
    r"\b(AAPL|TSLA|MSFT|AMZN|META|NVDA|GOOG|GOOGL|NFLX|SPY|QQQ|DOW|DJI|"
    r"IBIT|GLD|SLV|GOLD|SILVER|OIL|WTI|BRENT|"
    r"EUR|USD|JPY|GBP|CHF|CNY|FOREX)\b",
    re.IGNORECASE
)

def log1p(x: float) -> float:
    return math.log1p(max(0.0, x))

def violent_score(o: dict) -> float:
    # gros bougies = activité + volume, avec un minimum de liquidité
    vol5 = float(o.get("volume_5m_usd", 0) or 0)
    tx5  = float(o.get("tx_5m", 0) or 0)
    liq  = float(o.get("liquidity_usd", 0) or 0)
    top1 = float(o.get("top1_pct", 0) or 0)
    top5 = float(o.get("top5_pct", 0) or 0)

    # score principal
    s = 6.0 * log1p(vol5) + 4.0 * log1p(tx5) + 2.0 * log1p(liq)

    # pénalités whales (évite les trucs trop concentrés)
    if top5 > 70: s -= 6
    elif top5 > 60: s -= 4
    elif top5 > 50: s -= 2

    if top1 > 40: s -= 3
    elif top1 > 30: s -= 2

    # bonus si profile PUMP
    prof = str(o.get("profile", "") or "").upper()
    if prof == "PUMP": s += 2

    return s

rows = []
bad = 0

if not PATH.exists():
    raise SystemExit(f"❌ missing {PATH}")

for line in PATH.read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        o = json.loads(line)
    except Exception:
        bad += 1
        continue

    mint = (o.get("mint") or o.get("outputMint") or o.get("address") or "").strip()
    if not mint:
        continue

    sym  = str(o.get("symbol") or o.get("sym") or "").strip()
    name = str(o.get("name") or "").strip()
    blob = f"{sym} {name}".strip()

    # On affiche aussi un top "pur PUMP + anti-stocklike"
    is_stocklike = bool(STOCKLIKE.search(blob))

    vol5 = float(o.get("volume_5m_usd", 0) or 0)
    tx5  = float(o.get("tx_5m", 0) or 0)
    liq  = float(o.get("liquidity_usd", 0) or 0)
    top1 = float(o.get("top1_pct", 0) or 0)
    top5 = float(o.get("top5_pct", 0) or 0)
    prof = str(o.get("profile", "") or "").upper()

    sc = violent_score(o)

    rows.append((sc, prof, mint, sym, name, vol5, tx5, liq, top1, top5, is_stocklike))

rows.sort(reverse=True, key=lambda t: t[0])

print(f"[TOP_VIOLENT] rows={len(rows)} bad_json={bad}\n")

print("TOP 5 (global):")
for i, r in enumerate(rows[:5], 1):
    sc, prof, mint, sym, name, vol5, tx5, liq, top1, top5, is_stocklike = r
    print(f"{i}. score={sc:.3f} prof={prof:<6} mint={mint} stocklike={is_stocklike}")
    print(f"   sym={sym} name={name}")
    print(f"   vol5=${vol5:,.0f} tx5={tx5:.0f} liq=${liq:,.0f} top1={top1:.1f}% top5={top5:.1f}%")

print("\nTOP 5 (PUMP only + anti-stocklike):")
flt = [r for r in rows if r[1] == "PUMP" and not r[10]]
for i, r in enumerate(flt[:5], 1):
    sc, prof, mint, sym, name, vol5, tx5, liq, top1, top5, is_stocklike = r
    print(f"{i}. score={sc:.3f} prof={prof:<6} mint={mint}")
    print(f"   sym={sym} name={name}")
    print(f"   vol5=${vol5:,.0f} tx5={tx5:.0f} liq=${liq:,.0f} top1={top1:.1f}% top5={top5:.1f}%")
