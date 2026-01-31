import json, os
from pathlib import Path

IN_FILE  = os.getenv("READY_IN",  "ready_to_trade_rescored.jsonl")
OUT_FILE = os.getenv("READY_OUT", "ready_to_trade_ranked.jsonl")
TOP_K    = int(os.getenv("RANK_TOP_K", "5"))

# Gates (confirm trading only)
MIN_LIQ   = float(os.getenv("GATE_MIN_LIQ_USD", "30000"))
MAX_LIQ   = float(os.getenv("GATE_MAX_LIQ_USD", "1500000"))
MIN_TX1H  = float(os.getenv("GATE_MIN_TXNS_1H", "40"))
MIN_VOL24 = float(os.getenv("GATE_MIN_VOL_24H", "120000"))
MIN_CHG1H = float(os.getenv("GATE_MIN_CHG_1H", "2.0"))
MAX_CHG1H = float(os.getenv("GATE_MAX_CHG_1H", "30.0"))

# Weights v4
W_TX1H   = float(os.getenv("W_TX1H",   "0.40"))
W_VOL1H  = float(os.getenv("W_VOL1H",  "0.25"))
W_CHG1H  = float(os.getenv("W_CHG1H",  "0.15"))
W_LIQ    = float(os.getenv("W_LIQ",    "0.10"))
W_ORIGIN = float(os.getenv("W_ORIGIN", "0.10"))
W_ORCA   = float(os.getenv("W_ORCA",   "0.10"))
W_METEORA= float(os.getenv("W_METEORA","0.08"))

def norm(x, lo, hi):
    if x is None: return 0.0
    try: x = float(x)
    except: return 0.0
    if hi <= lo: return 0.0
    if x <= lo: return 0.0
    if x >= hi: return 1.0
    return (x - lo) / (hi - lo)

def get_origin(o):
    mint = (o.get("mint") or "").strip()
    if mint.endswith("pump"):
        return "pumpfun"
    if o.get("pump_sig") == "X":
        return "pumpfun"
    return "raydium_direct"

def get_confirmed_on(o):
    confirmed = set()
    dex = (o.get("dex_id") or o.get("dex") or "").lower()
    if "raydium" in dex: confirmed.add("raydium")
    if "orca" in dex: confirmed.add("orca")
    dexes = o.get("dexes")
    if isinstance(dexes, list):
        for d in dexes:
            if isinstance(d, str):
                dl = d.lower()
                if "raydium" in dl: confirmed.add("raydium")
                if "orca" in dl: confirmed.add("orca")
    return sorted(confirmed)

def penalties(o):
    p = 0.0
    mc = o.get("market_cap") or o.get("mcap") or o.get("fdv")
    try:
        if mc and float(mc) > 8_000_000:
            p += 0.20
    except: pass
    liq = o.get("liq_usd") or o.get("liquidity_usd")
    vol24 = o.get("vol_24h") or o.get("volume_24h")
    try:
        if liq and vol24 and float(vol24) > 12 * float(liq):
            p += 0.20
    except: pass
    return p

if not Path(IN_FILE).exists():
    print("❌ IN_FILE not found:", IN_FILE)
    raise SystemExit(2)

rows = []
with open(IN_FILE, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)

        liq   = o.get("liq_usd") or o.get("liquidity_usd") or 0
        vol24 = o.get("vol_24h") or o.get("volume_24h") or 0
        vol1h = o.get("vol_1h") or 0
        tx1h  = o.get("txns_1h") or o.get("tx_1h") or 0
        chg1h = o.get("chg_1h") or o.get("change_1h") or 0

        try:
            liq=float(liq); vol24=float(vol24); vol1h=float(vol1h); tx1h=float(tx1h); chg1h=float(chg1h)
        except:
            continue

        if liq < MIN_LIQ or liq > MAX_LIQ: continue
        if vol24 < MIN_VOL24: continue
        if tx1h < MIN_TX1H: continue
        if chg1h < MIN_CHG1H or chg1h > MAX_CHG1H: continue

        origin = get_origin(o)
        confirmed_on = get_confirmed_on(o)

        origin_bonus = 1.0 if origin == "pumpfun" else 0.0
        orca_bonus   = 0.5 if "orca" in confirmed_on else 0.0
        meteora_bonus= 0.35 if "meteora" in confirmed_on else 0.0

        s = (
            W_TX1H   * norm(tx1h,  40, 300) +
            W_VOL1H  * norm(vol1h, 10_000, 150_000) +
            W_CHG1H  * norm(chg1h, 2.0, 25.0) +
            W_LIQ    * norm(liq,  30_000, 500_000) +
            W_ORIGIN * origin_bonus +
            W_ORCA   * orca_bonus +
            W_METEORA* meteora_bonus
        )
        s -= penalties(o)

        o["origin"] = origin
        o["confirmed_on"] = confirmed_on
        o["score_v4"] = round(s, 4)
        rows.append(o)

rows.sort(key=lambda x: x.get("score_v4", 0), reverse=True)
rows = rows[:TOP_K]

with open(OUT_FILE, "w", encoding="utf-8") as w:
    for o in rows:
        w.write(json.dumps(o) + "\n")

print(f"OK: kept={len(rows)} -> {OUT_FILE}")
for i,o in enumerate(rows, 1):
    print(i, o.get("mint"), "score_v4=", o.get("score_v4"),
          "origin=", o.get("origin"),
          "dex=", o.get("dex_id"),
          "confirmed_on=", o.get("confirmed_on"),
          "liq=", o.get("liquidity_usd"),
          "vol24=", o.get("vol_24h"),
          "tx1h=", o.get("txns_1h"),
          "chg1h=", o.get("chg_1h"))
