import requests
from typing import Optional

DEX_TIMEOUT = float(__import__("os").getenv("DEX_TIMEOUT_S", "10"))

class DexScreenerPriceFeed:
    """
    Price feed sync sans API key.
    Utilise DexScreener: https://api.dexscreener.com/latest/dex/tokens/<mint>
    Retourne priceUsd float ou None.
    """
    def __init__(self):
        self.s = requests.Session()

    def get_price(self, mint: str) -> Optional[float]:
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            r = self.s.get(url, timeout=DEX_TIMEOUT)
            if r.status_code != 200:
                return None
            j = r.json()
            pairs = j.get("pairs") or []
            if not pairs:
                return None
            # prendre le meilleur pair par liquidité USD
            best = max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0.0))
            px = best.get("priceUsd")
            return float(px) if px else None
        except Exception:
            return None
