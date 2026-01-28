import os
import requests

JUP = (os.getenv("JUPITER_BASE_URL") or "https://api.jup.ag").rstrip("/")
KEY = (os.getenv("JUPITER_API_KEY") or "").strip()
TIMEOUT = int(os.getenv("PRICE_TIMEOUT_S", "20"))

def _headers():
    h = {"accept": "application/json"}
    if KEY:
        h["x-api-key"] = KEY
    return h

def get_prices(mints: list[str]) -> dict:
    mints = [m for m in (mints or []) if m]
    if not mints:
        return {}
    # Price v3: /price/v3?ids=A,B,C (max 50)
    ids = ",".join(mints[:50])
    url = f"{JUP}/price/v3"
    r = requests.get(url, params={"ids": ids}, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json() or {}
    # data = { "<mint>": { "usdPrice": ..., "decimals": ..., ... }, ... }
    return data

def get_price(mint: str) -> float:
    mint = (mint or "").strip()
    if not mint:
        raise ValueError("mint empty")
    data = get_prices([mint])
    info = data.get(mint)
    if not info or info.get("usdPrice") is None:
        raise ValueError(f"price unavailable for {mint}")
    return float(info["usdPrice"])

def get_sol_usd() -> float:
    SOL = "So11111111111111111111111111111111111111112"
    return get_price(SOL)
