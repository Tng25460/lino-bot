from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx


class BirdeyeAsyncClient:
    """
    Birdeye public API (Solana)
    Base: https://public-api.birdeye.so

    Headers requis dans la pratique:
      - X-API-KEY
      - x-chain: solana
      - accept: application/json
    """

    def __init__(self, api_key: str, base_url: str = "https://public-api.birdeye.so", chain: str = "solana"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.chain = chain
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=20.0)

    def _headers(self) -> Dict[str, str]:
        return {
            "X-API-KEY": self.api_key,
            "x-chain": self.chain,
            "accept": "application/json",
        }

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        r = await self._client.get(path, headers=self._headers(), params=params or {})
        # Laisse le message clair en cas d'erreur
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code} for {self.base_url}{path} | body={r.text}")
        return r.json()

    async def get_new_tokens(self, limit: int = 10) -> Dict[str, Any]:
        # D'après l’endpoint: /defi/v2/tokens/new_listing?limit=...
        # On met la chain en header, pas en query (ça évite les 400 chelous).
        return await self._get("/defi/v2/tokens/new_listing", params={"limit": int(limit)})

    async def get_multi_price(self, list_address: List[str]) -> Dict[str, Any]:
        # /defi/multi_price?list_address=...
        return await self._get("/defi/multi_price", params={"list_address": ",".join(list_address)})

    async def aclose(self) -> None:
        await self._client.aclose()
