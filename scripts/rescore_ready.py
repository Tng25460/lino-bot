import json
import math
import sys

IN = sys.argv[1] if len(sys.argv) > 1 else "ready_to_trade_scored.jsonl"
OUT = sys.argv[2] if len(sys.argv) > 2 else "ready_to_trade_rescored.jsonl"

def norm(x, lo, hi):
    if x is None: return 0.0
    try:
        x = float(x)
    except:
        return 0.0
    if x <= lo: return 0.0
    if x >= hi: return 1.0
    return (x - lo) / (hi - lo)

rows = []
with open(IN, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if not line.strip(): continue
        o = json.loads(line)

        liq = o.get("liq_usd") or o.get("liquidity_usd")
        vol = o.get("vol_24h") or o.get("volume_24h")
        tx1h = o.get("txns_1h") or o.get("tx_1h")
        chg = o.get("chg_1h") or o.get("change_1h")

        # Normalisations (bornes réalistes Pump/Fresh)
        n_tx  = norm(tx1h, 20, 300)       # activité réelle
        n_vol = norm(vol, 50_000, 1_500_000)
        n_chg = norm(chg, 2, 20)          # éviter trop tard
        n_liq = norm(liq, 30_000, 800_000)

        score2 = (
            0.40 * n_tx +
            0.30 * n_vol +
            0.20 * n_chg +
            0.10 * n_liq
        ) * 10.0

        o["score2"] = round(score2, 4)
        rows.append(o)

rows.sort(key=lambda x: x.get("score2", 0), reverse=True)

with open(OUT, "w", encoding="utf-8") as w:
    for o in rows:
        w.write(json.dumps(o, ensure_ascii=False) + "\n")

print(f"OK: rescored {len(rows)} rows -> {OUT}")
if rows:
    top = rows[0]
    print("TOP:", {k: top.get(k) for k in ("mint","score","score2","liq_usd","vol_24h","txns_1h","chg_1h")})
