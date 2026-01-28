from __future__ import annotations
import httpx
from typing import Any, Dict, List, Optional

class GeckoTerminalAsync:
    def __init__(self, base_url: str = "https://api.geckoterminal.com/api/v2", timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout, headers={"accept": "application/json"})

    async def aclose(self):
        await self._client.aclose()

    async def get_new_pools(self, network: str = "solana", page_size: int = 10) -> Dict[str, Any]:
        # https://api.geckoterminal.com/api/v2/networks/solana/new_pools?page[size]=10
        r = await self._client.get(
            f"{self.base_url}/networks/{network}/new_pools",
            params={"page[size]": int(page_size)},
        )
        r.raise_for_status()
        return r.json()
