import json, sys, time, requests

IN  = sys.argv[1] if len(sys.argv)>1 else "ready_to_trade_ranked.jsonl"
OUT = sys.argv[2] if len(sys.argv)>2 else "ready_to_trade_ranked_orca.jsonl"

API = "https://api.dexscreener.com/latest/dex/tokens/"

def fetch_pairs(mint: str):
    r = requests.get(API + mint, timeout=12)
    if r.status_code != 200:
        return None, f"http {r.status_code}"
    j = r.json()
    pairs = j.get("pairs") or []
    return pairs, None

def norm_dex(d):
    d = (d or "").lower()
    if "raydium" in d: return "raydium"
    if "orca" in d: return "orca"
    if "meteora" in d: return "meteora"
    return d

rows = []
with open(IN, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if not line.strip(): continue
        rows.append(json.loads(line))

out = []
for i,o in enumerate(rows,1):
    mint = o.get("mint")
    if not mint:
        continue

    pairs, err = fetch_pairs(mint)
    if err:
        o["dexes"] = o.get("dexes") or []
        o["dexes_err"] = err
        out.append(o)
        continue

    dexes = []
    best = None
    best_liq = -1

    for p in pairs:
        dex = norm_dex(p.get("dexId"))
        if dex:
            dexes.append(dex)
        liq = (p.get("liquidity") or {}).get("usd") or 0
        try:
            liq = float(liq)
        except:
            liq = 0
        if liq > best_liq:
            best_liq = liq
            best = p

    o["dexes"] = sorted(list(set(dexes)))
    # Optionnel: si tu veux “best pair” comme source de price/liquidity
    if best:
        o["best_pair_dex"] = norm_dex(best.get("dexId"))
        o["best_pair_liq_usd"] = (best.get("liquidity") or {}).get("usd")
        o["best_pair_address"] = best.get("pairAddress")

    out.append(o)
    time.sleep(0.25)  # soft rate limit

with open(OUT, "w", encoding="utf-8") as w:
    for o in out:
        w.write(json.dumps(o) + "\n")

print(f"OK: enriched dexes -> {OUT} rows={len(out)}")
for o in out[:5]:
    print("SAMPLE", o.get("mint"), "dexes=", o.get("dexes"), "best=", o.get("best_pair_dex"))
