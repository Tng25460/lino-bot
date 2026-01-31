from __future__ import annotations
import httpx
from typing import Dict, Any, List, Optional

class JupiterPriceV3Async:
    def __init__(self, api_key: str, base_url: str = "https://api.jup.ag", timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"accept": "application/json", "x-api-key": api_key},
        )

    async def aclose(self):
        await self._client.aclose()

    async def get_prices_usd(self, mints: List[str]) -> Dict[str, Any]:
        # https://api.jup.ag/price/v3?ids=...
        ids = ",".join(mints)
        r = await self._client.get(f"{self.base_url}/price/v3", params={"ids": ids})
        r.raise_for_status()
        return r.json()
