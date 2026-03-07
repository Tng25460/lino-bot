#!/usr/bin/env python3
import os, json, time, math
from pathlib import Path
import requests

READY_IN  = Path(os.getenv("READY_IN", "ready_to_trade.jsonl"))
OUT       = Path(os.getenv("READY_OUT", "ready_to_trade_scored.jsonl"))

LIMIT     = int(os.getenv("READY_LIMIT", "200"))
SLEEP     = float(os.getenv("READY_SLEEP", "0.12"))
TIMEOUT   = float(os.getenv("DS_TIMEOUT", "8"))
RETRIES   = int(os.getenv("DS_RETRIES", "2"))

# Gates (hard)
MIN_LIQ_USD    = float(os.getenv("MIN_LIQ_USD", "15000"))
MIN_VOL5M_USD  = float(os.getenv("MIN_VOL5M_USD", "3000"))
MIN_CHG5M_PCT  = float(os.getenv("MIN_CHG5M_PCT", "5"))
MAX_CHG5M_PCT  = float(os.getenv("MAX_CHG5M_PCT", "70"))
MIN_CHG1H_PCT  = float(os.getenv("MIN_CHG1H_PCT", "10"))
DEX_ALLOW      = set(x.strip() for x in os.getenv("DEX_ALLOW", "raydium").lower().split(",") if x.strip())

# Keep condition
SCORE_MIN      = float(os.getenv("SCORE_MIN", "7.2"))

def clamp(x,a,b): return a if x<a else b if x>b else x
def sf(x, d=0.0):
    try: return float(x)
    except: return d

sess = requests.Session()
sess.headers.update({"accept": "application/json", "user-agent": "lino-score/1.0"})

def load_ready():
    out=[]
    if not READY_IN.exists():
        print("ERR missing", READY_IN)
        return out
    with READY_IN.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try:
                j=json.loads(line)
            except Exception:
                continue
            if isinstance(j, dict):
                out.append(j)
            if len(out) >= LIMIT:
                break
    return out

def fetch_ds(mint: str):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
    last_err = None
    for _ in range(RETRIES+1):
        try:
            r = sess.get(url, timeout=TIMEOUT)
            if r.status_code != 200:
                last_err = f"http_{r.status_code}"
                time.sleep(0.15)
                continue
            j = r.json() or {}
            pairs = j.get("pairs") or []
            if not pairs:
                return None, "no_pairs"
            # pick best pair by liquidity.usd
            best=None
            best_liq=-1.0
            for p in pairs:
                liq = sf(((p.get("liquidity") or {}).get("usd")), 0.0)
                if liq > best_liq:
                    best_liq = liq
                    best = p
            return best, ""
        except Exception as e:
            last_err = f"exc_{type(e).__name__}"
            time.sleep(0.2)
    return None, (last_err or "ds_fail")

def gate_and_score(pair):
    """
    Returns: (ok_keep:bool, score:float, why:str, dbg:dict)
    """
    if not pair:
        return False, -1.0, "no_pair", {}

    dex = (pair.get("dexId") or "").lower()
    if DEX_ALLOW and dex and dex not in DEX_ALLOW:
        return False, -1.0, f"dex_{dex}", {"dex": dex}

    liq = sf(((pair.get("liquidity") or {}).get("usd")), 0.0)
    vol5m = sf(((pair.get("volume") or {}).get("m5")), 0.0)
    chg5m = sf(((pair.get("priceChange") or {}).get("m5")), 0.0)
    chg1h = sf(((pair.get("priceChange") or {}).get("h1")), 0.0)

    # hard gates
    if liq < MIN_LIQ_USD:
        return False, -1.0, "liq", {"liq": liq}
    if vol5m < MIN_VOL5M_USD:
        return False, -1.0, "vol5m", {"vol5m": vol5m}
    if chg5m < MIN_CHG5M_PCT:
        return False, -1.0, "chg5m_low", {"chg5m": chg5m}
    if chg5m > MAX_CHG5M_PCT:
        return False, -1.0, "chg5m_high", {"chg5m": chg5m}
    if chg1h < MIN_CHG1H_PCT:
        return False, -1.0, "chg1h", {"chg1h": chg1h}

    # score (simple + stable)
    # liquidity component (log)
    s_liq = clamp(math.log10(liq + 1.0), 0.0, 6.0)          # 0..6
    # volume component (log)
    s_vol = clamp(math.log10(vol5m + 1.0), 0.0, 6.0)        # 0..6
    # momentum component
    s_mom = clamp((chg5m / 10.0) + (chg1h / 40.0), 0.0, 6.0)# 0..6

    score = (0.45*s_mom + 0.30*s_vol + 0.25*s_liq) * 3.0    # ~0..18
    ok = score >= SCORE_MIN
    dbg = {"dex": dex, "liq": liq, "vol5m": vol5m, "chg5m": chg5m, "chg1h": chg1h,
           "s_liq": round(s_liq,3), "s_vol": round(s_vol,3), "s_mom": round(s_mom,3)}
    return ok, float(score), ("ok" if ok else "score"), dbg

def main():
    ready = load_ready()
    print(f"READY_IN={READY_IN} total={len(ready)} limit={LIMIT} timeout={TIMEOUT}s sleep={SLEEP}s")
    if not ready:
        OUT.write_text("", encoding="utf-8")
        print("OUT=", OUT, "kept=0 (empty input)")
        return 0

    OUT.unlink(missing_ok=True)

    stats = {"kept":0, "total":0, "no_pairs":0, "liq":0, "vol5m":0, "chg5m_low":0, "chg5m_high":0, "chg1h":0, "dex":0, "score":0, "ds_fail":0, "no_pair":0}
    all_lines = 0

    with OUT.open("w", encoding="utf-8") as fo:
        for c in ready:
            mint = (c.get("mint") or c.get("outputMint") or c.get("address") or "").strip()
            if not mint:
                continue

            pair, why_ds = fetch_ds(mint)
            if why_ds:
                stats["no_pairs" if why_ds=="no_pairs" else "ds_fail"] += 1

            ok, score, why, dbg = gate_and_score(pair)
            if why.startswith("dex_"):
                stats["dex"] += 1
            elif why in stats:
                stats[why] += 1
            elif why_ds in stats:
                stats[why_ds] += 1

            row = dict(c)
            row["mint"] = mint
            row["score"] = round(score, 4)
            row["why"] = (why_ds if why_ds else why)
            row["ds"] = dbg
            row["pair"] = {
                "dexId": (pair.get("dexId") if pair else None),
                "pairAddress": (pair.get("pairAddress") if pair else None),
                "baseSymbol": ((pair.get("baseToken") or {}).get("symbol") if pair else None),
                "quoteSymbol": ((pair.get("quoteToken") or {}).get("symbol") if pair else None),
                "priceUsd": (pair.get("priceUsd") if pair else None),
            } if pair else None

            fo.write(json.dumps(row, ensure_ascii=False) + "\n")
            all_lines += 1
            stats["total"] += 1
            if ok:
                stats["kept"] += 1

            if SLEEP > 0:
                time.sleep(SLEEP)

    print("OUT=", OUT, "lines=", all_lines, "kept=", stats["kept"])
    print("STATS:", json.dumps(stats, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
