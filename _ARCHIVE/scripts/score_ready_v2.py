#!/usr/bin/env python3
import os, sys, json, math, argparse
from typing import Any, Dict
import os

# --- IO from env (so we can write into state/)
READY_IN = os.getenv('READY_IN', 'state/ready_to_trade_enriched.jsonl')
READY_OUT = os.getenv('READY_OUT', 'state/ready_to_trade_scored.jsonl')


def fnum(x, default=0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)

def pick(d: Dict[str, Any], *paths, default=None):
    # paths can be strings (direct keys) or tuples for nested keys
    for p in paths:
        cur = d
        ok = True
        if isinstance(p, tuple):
            for k in p:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    ok = False
                    break
            if ok:
                return cur
        else:
            if isinstance(cur, dict) and p in cur:
                return cur[p]
    return default

def get_metrics(j: Dict[str, Any]) -> Dict[str, Any]:
    # Many possible DexScreener shapes; be permissive.
    mint = j.get("mint") or j.get("baseToken", {}).get("address") or ""
    symbol = j.get("symbol") or j.get("baseToken", {}).get("symbol") or ""

    liq = pick(j, ("liquidity","usd"), "liquidityUsd", "liquidity_usd", "liq", "liq_usd", default=0.0)
    vol24 = pick(j, ("volume","h24"), "volume24h", "vol24", "vol_24h", default=0.0)

    # txns / change often nested
    tx1h = pick(j, ("txns","h1","buys"), "txns_1h", default=None)
    if tx1h is None:
        tx1h = pick(j, "tx1h", "txns1h", "txns_1h", default=0.0)
    else:
        # if it's buys only, also add sells if present
        sells = pick(j, ("txns","h1","sells"), default=0.0)
        tx1h = fnum(tx1h,0.0) + fnum(sells,0.0)

    chg1h = pick(j, ("priceChange","h1"), "change1h", "chg1h", "chg_1h", default=0.0)

    fdv = pick(j, "fdv", "fullyDilutedValuation", default=0.0)
    mcap = pick(j, "marketCap", "market_cap", "mcap", default=0.0)

    dex = pick(j, "dexId", "dex_id", "dex", "dex_id", default=None)
    if dex is None:
        # sometimes "dexes": [...]
        dex = pick(j, "dexes", default=None)

    return {
        "mint": mint,
        "symbol": symbol,
        "liq": fnum(liq,0.0),
        "vol24": fnum(vol24,0.0),
        "tx1h": fnum(tx1h,0.0),
        "chg1h": fnum(chg1h,0.0),
        "fdv": fnum(fdv,0.0),
        "mcap": fnum(mcap,0.0),
        "dex": dex,
    }

def score(m: Dict[str, Any]) -> float:
    # Simple, robust, monotonic score. Missing fields just contribute 0.
    liq = max(m["liq"], 0.0)
    vol24 = max(m["vol24"], 0.0)
    tx1h = max(m["tx1h"], 0.0)
    chg1h = m["chg1h"]

    s = 0.0
    # log scale so early tokens don't get nuked
    if liq > 0:
        s += min(1.0, math.log10(1.0 + liq) / 6.0)         # ~ up to 1 at 1M
    if vol24 > 0:
        s += min(1.0, math.log10(1.0 + vol24) / 7.0)       # ~ up to 1 at 10M
    if tx1h > 0:
        s += min(1.0, math.log10(1.0 + tx1h) / 3.0)        # ~ up to 1 at 1000 tx
    # reward positive momentum a bit, but don't kill negatives too hard
    s += max(-0.3, min(0.7, chg1h / 100.0))                # -30%..+70% range

    # tiny bonus if dex is known
    if m.get("dex"):
        s += 0.05

    # normalize to 0..1.5 roughly
    return max(0.0, s)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="ready_to_trade_enriched.jsonl")
    ap.add_argument("--out", dest="out", default="ready_to_trade_scored.jsonl")
    ap.add_argument("--limit", type=int, default=2000000)
    args = ap.parse_args()

    # gates via env ONLY
    score_min      = float(os.getenv("SCORE_MIN", "0.0"))
    min_liq        = float(os.getenv("SCORE_MIN_LIQ", "0"))
    min_vol24      = float(os.getenv("SCORE_MIN_VOL24", "0"))
    min_tx1h       = float(os.getenv("SCORE_MIN_TX1H", "0"))
    min_chg1h      = float(os.getenv("SCORE_MIN_CHG1H", "-999"))
    max_fdv        = float(os.getenv("SCORE_MAX_FDV", "1e18"))
    max_mcap       = float(os.getenv("SCORE_MAX_MCAP", "1e18"))
    require_dex    = os.getenv("SCORE_REQUIRE_DEX", "0") == "1"
    force_any      = os.getenv("SCORE_FORCE_ANY", "0") == "1"

    kept = 0
    total = 0
    bad = 0

    with open(args.inp, "r", encoding="utf-8") as f, open(args.out, "w", encoding="utf-8") as g:
        for line in f:
            if total >= args.limit:
                break
            t = line.strip()
            if not t:
                continue
            total += 1
            try:
                j = json.loads(t)
                if not isinstance(j, dict):
                    bad += 1
                    continue
            except Exception:
                bad += 1
                continue

            m = get_metrics(j)
            mint = m["mint"]
            if not mint:
                continue

            if require_dex and not m.get("dex"):
                continue

            # gates (missing metrics == 0)
            if m["liq"] < min_liq:
                continue
            if m["vol24"] < min_vol24:
                continue
            if m["tx1h"] < min_tx1h:
                continue
            if m["chg1h"] < min_chg1h:
                continue
            if m["fdv"] > max_fdv:
                continue
            if m["mcap"] > max_mcap:
                continue

            sc = score(m)

            if sc < score_min and not force_any:
                continue

            out = dict(j)
            out["mint"] = mint
            if m["symbol"]:
                out["symbol"] = m["symbol"]
            out["score_used"] = float(sc)
            out["liq"] = float(m["liq"])
            out["vol24"] = float(m["vol24"])
            out["tx1h"] = float(m["tx1h"])
            out["chg1h"] = float(m["chg1h"])
            out["fdv"] = float(m["fdv"])
            out["mcap"] = float(m["mcap"])
            out["dexes"] = m.get("dex")

            g.write(json.dumps(out, ensure_ascii=False) + "\n")
            kept += 1

    print(f"READY_IN={args.inp} total={total} bad_json={bad}", flush=True)
    print(f"scored: {kept} of {total} -> {args.out} bytes={os.path.getsize(args.out) if os.path.exists(args.out) else 0}", flush=True)

if __name__ == "__main__":
    main()
