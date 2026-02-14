import json, time
import requests

OUT_STATE = "state/ready_pump_early.jsonl"
OUT_ROOT  = "ready_to_trade.jsonl"

URLS = [
    ("token-boosts/top",    "https://api.dexscreener.com/token-boosts/top/v1"),
    ("token-boosts/latest", "https://api.dexscreener.com/token-boosts/latest/v1"),
    ("token-profiles",      "https://api.dexscreener.com/token-profiles/latest/v1"),
]

def fetch(url):
    r = requests.get(url, timeout=25)
    r.raise_for_status()
    return r.json()

def main():
    seen = []
    seen_set = set()
    now = int(time.time())

    for src, url in URLS:
        try:
            data = fetch(url)
        except Exception as e:
            print(f"[dex] FAIL src={src} err={e}")
            continue

        # data peut être list ou dict
        items = data if isinstance(data, list) else data.get("data") or data.get("tokens") or data.get("pairs") or []
        if not isinstance(items, list):
            # parfois c'est un dict -> wrap
            items = [items]

        for it in items:
            if not isinstance(it, dict):
                continue
            chain = (it.get("chainId") or it.get("chain") or "").strip().lower()
            if chain != "solana":
                continue
            mint = (it.get("tokenAddress") or it.get("address") or it.get("baseToken", {}).get("address") or "").strip()
            if not mint:
                continue
            if mint in seen_set:
                continue
            seen_set.add(mint)
            seen.append({
                "mint": mint,
                "src": src,
                "ts": now
            })

    # écrit state + root (format JSONL minimal accepté par ton trader_exec)
    with open(OUT_STATE, "w", encoding="utf-8") as f:
        for row in seen[:250]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with open(OUT_ROOT, "w", encoding="utf-8") as f:
        for row in seen[:250]:
            f.write(json.dumps({"mint": row["mint"]}, ensure_ascii=False) + "\n")

    print(f"[dex] DONE mints={len(seen)} OUT_STATE={OUT_STATE} OUT_ROOT={OUT_ROOT}")

if __name__ == "__main__":
    main()
