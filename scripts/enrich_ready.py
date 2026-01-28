#!/usr/bin/env python3
import os, json, time, random
from pathlib import Path
import requests

READY_IN   = Path(os.getenv("READY_IN", "ready_to_trade.jsonl"))
OUT        = Path(os.getenv("READY_OUT", "ready_to_trade_enriched.jsonl"))
LIMIT      = int(os.getenv("READY_LIMIT", "200"))
SLEEP      = float(os.getenv("READY_SLEEP", "0.12"))
TIMEOUT    = float(os.getenv("DS_TIMEOUT", "8"))
RETRIES    = int(os.getenv("DS_RETRIES", "2"))

def safe_float(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d

def pick_best_pair(pairs):
    best = None
    best_liq = -1.0
    best_v24 = -1.0
    for p in pairs or []:
        liq = safe_float(((p.get("liquidity") or {}).get("usd")), 0.0)
        v24 = safe_float(((p.get("volume") or {}).get("h24")), 0.0)
        if liq > best_liq or (liq == best_liq and v24 > best_v24):
            best = p
            best_liq = liq
            best_v24 = v24
    return best

sess = requests.Session()
sess.headers.update({"accept":"application/json", "user-agent":"lino-enricher/1.0"})

def fetch_ds(mint: str):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
    last_err = None
    for k in range(RETRIES + 1):
        try:
            r = sess.get(url, timeout=TIMEOUT)
            if r.status_code != 200:
                last_err = f"http={r.status_code} body={r.text[:200]}"
            else:
                return r.json() or {}
        except Exception as e:
            last_err = str(e)
        time.sleep(0.25 + 0.25*k + random.random()*0.1)
    return {"_error": last_err}

def iter_ready(path: Path, limit: int):
    n = 0
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if n >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if not isinstance(o, dict):
                continue
            mint = (o.get("mint") or o.get("outputMint") or "").strip()
            if not mint:
                continue
            yield o
            n += 1

def main():
    if not READY_IN.exists():
        raise SystemExit(f"missing {READY_IN}")

    OUT.write_text("", encoding="utf-8")

    total = 0
    ok = 0

    for o in iter_ready(READY_IN, LIMIT):
        total += 1
        mint = (o.get("mint") or o.get("outputMint") or "").strip()

        ds = fetch_ds(mint)
        pairs = (ds or {}).get("pairs") or []
        best = pick_best_pair(pairs)

        feat = {
            "ts": int(o.get("ts") or time.time()),
            "mint": mint,
            "symbol": (o.get("symbol") or (best or {}).get("baseToken",{}).get("symbol") or "").strip(),
            "creator": o.get("creator"),
            "pump_sig": o.get("pump_sig"),
            "mint_sig": o.get("mint_sig"),
            "fetched_at": int(time.time()),
            "ds_ok": bool(best),
            "ds_error": (ds or {}).get("_error"),
            "dex_id": ((best or {}).get("dexId") or "").lower(),
            "chain_id": (best or {}).get("chainId"),
            "pair_address": (best or {}).get("pairAddress"),
            "price_usd": safe_float((best or {}).get("priceUsd"), 0.0),
            "liquidity_usd": safe_float(((best or {}).get("liquidity") or {}).get("usd"), 0.0),
            "fdv": safe_float((best or {}).get("fdv"), 0.0),
            "market_cap": safe_float((best or {}).get("marketCap"), 0.0),
            "vol_5m": safe_float(((best or {}).get("volume") or {}).get("m5"), 0.0),
            "vol_1h": safe_float(((best or {}).get("volume") or {}).get("h1"), 0.0),
            "vol_24h": safe_float(((best or {}).get("volume") or {}).get("h24"), 0.0),
            "chg_5m": safe_float((((best or {}).get("priceChange") or {}).get("m5")), 0.0),
            "chg_1h": safe_float((((best or {}).get("priceChange") or {}).get("h1")), 0.0),
            "chg_24h": safe_float((((best or {}).get("priceChange") or {}).get("h24")), 0.0),
            "txns_5m": int(
                safe_float(((((best or {}).get("txns") or {}).get("m5") or {}).get("buys")), 0.0) +
                safe_float(((((best or {}).get("txns") or {}).get("m5") or {}).get("sells")), 0.0)
            ),
            "txns_1h": int(
                safe_float(((((best or {}).get("txns") or {}).get("h1") or {}).get("buys")), 0.0) +
                safe_float(((((best or {}).get("txns") or {}).get("h1") or {}).get("sells")), 0.0)
            ),
        }

        if feat["ds_ok"]:
            ok += 1

        with OUT.open("a", encoding="utf-8") as w:
            w.write(json.dumps(feat, ensure_ascii=False) + "\n")

        if SLEEP > 0:
            time.sleep(SLEEP)

    print("READY_IN=", str(READY_IN), "limit=", LIMIT, "total=", total, "ds_ok=", ok)
    print("OUT=", str(OUT), "bytes=", (OUT.stat().st_size if OUT.exists() else 0))

if __name__ == "__main__":
    main()
