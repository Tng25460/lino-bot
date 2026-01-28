import json
import os
import time
from pathlib import Path

import requests

META = Path(os.getenv("TRADER_LAST_META_FILE", "last_swap_meta.json"))
JUP = (os.getenv("JUPITER_BASE_URL") or "https://api.jup.ag").rstrip("/")
KEY = (os.getenv("JUPITER_API_KEY") or "").strip()

POLL_S = float(os.getenv("PUMP_POLL_S","3"))

STOP_LOSS = float(os.getenv("PUMP_STOP_LOSS_PCT","25"))/100.0
TP1 = float(os.getenv("PUMP_TP1_PCT","30"))/100.0
TP2 = float(os.getenv("PUMP_TP2_PCT","60"))/100.0
TP3 = float(os.getenv("PUMP_TP3_PCT","100"))/100.0
TP_SELL_PCT = float(os.getenv("PUMP_TP_SELL_PCT","25"))

TRAIL = float(os.getenv("PUMP_TRAIL_FROM_PEAK_PCT","22"))/100.0
TIME_STOP_S = int(os.getenv("PUMP_TIME_STOP_S","900"))

def headers():
    h={"accept":"application/json"}
    if KEY:
        h["x-api-key"]=KEY
    return h

def price_usdc(mint: str) -> float:
    # Jupiter price v2
    r = requests.get(f"{JUP}/price/v2", params={"ids": mint}, headers=headers(), timeout=20)
    r.raise_for_status()
    j = r.json()
    data = (j.get("data") or {}).get(mint) or {}
    p = data.get("price")
    return float(p or 0.0)

def main():
    if not META.exists():
        raise SystemExit("❌ meta missing")

    meta = json.loads(META.read_text(encoding="utf-8"))
    mint = (meta.get("mint") or "").strip()
    if not mint:
        raise SystemExit("❌ mint missing in meta")

    entry = float(meta.get("entry_price_usdc") or 0.0)
    if entry <= 0:
        # fallback: take current price as entry
        entry = price_usdc(mint)
        meta["entry_price_usdc"] = entry
        META.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print("🔥 pump_rider start")
    print("   mint=", mint[:6]+"...", "entry_usdc=", entry)

    start = time.time()
    peak = entry
    sold_steps = set()

    while True:
        p = price_usdc(mint)
        if p <= 0:
            time.sleep(POLL_S)
            continue

        if p > peak:
            peak = p

        pnl = (p/entry) - 1.0
        dd = (peak/p) - 1.0 if p > 0 else 0

        print(f"   price={p:.8f} pnl={pnl*100:+.1f}% peak={peak:.8f} dd={dd*100:.1f}%")

        # hard stop loss
        if pnl <= -STOP_LOSS:
            print("🧯 STOP LOSS -> sell 100%")
            os.environ["SELL_MINT"]=mint
            os.environ["SELL_PCT"]="100"
            os.system("PYTHONPATH=. python src/trader_sell.py")
            return

        # take profit steps
        if pnl >= TP1 and "tp1" not in sold_steps:
            print("✅ TP1 -> sell", TP_SELL_PCT, "%")
            sold_steps.add("tp1")
            os.environ["SELL_MINT"]=mint
            os.environ["SELL_PCT"]=str(TP_SELL_PCT)
            os.system("PYTHONPATH=. python src/trader_sell.py")

        if pnl >= TP2 and "tp2" not in sold_steps:
            print("✅ TP2 -> sell", TP_SELL_PCT, "%")
            sold_steps.add("tp2")
            os.environ["SELL_MINT"]=mint
            os.environ["SELL_PCT"]=str(TP_SELL_PCT)
            os.system("PYTHONPATH=. python src/trader_sell.py")

        if pnl >= TP3 and "tp3" not in sold_steps:
            print("✅ TP3 -> sell", TP_SELL_PCT, "%")
            sold_steps.add("tp3")
            os.environ["SELL_MINT"]=mint
            os.environ["SELL_PCT"]=str(TP_SELL_PCT)
            os.system("PYTHONPATH=. python src/trader_sell.py")

        # trailing stop (exit remaining)
        if pnl > 0.05 and dd >= TRAIL:
            print("🏁 TRAILING STOP -> sell remaining 100%")
            os.environ["SELL_MINT"]=mint
            os.environ["SELL_PCT"]="100"
            os.system("PYTHONPATH=. python src/trader_sell.py")
            return

        # time stop (no pump)
        if time.time() - start >= TIME_STOP_S and pnl < 0.15:
            print("⏳ TIME STOP -> sell 100% (no pump)")
            os.environ["SELL_MINT"]=mint
            os.environ["SELL_PCT"]="100"
            os.system("PYTHONPATH=. python src/trader_sell.py")
            return

        time.sleep(POLL_S)

if __name__ == "__main__":
    main()
