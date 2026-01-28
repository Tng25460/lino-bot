from __future__ import annotations

import asyncio
import random
from typing import Any, Iterable, List, Optional

from core.solana_rpc_async import SolanaRPCAsync, RpcResponseError


class SolanaRPCPool:
    """
    Wrapper that tries multiple RPC endpoints.
    - round-robin-ish selection
    - on 429 / transient errors => retry with another endpoint
    """

    def __init__(
        self,
        rpc_urls: Iterable[str],
        *,
        timeout_s: float = 20.0,
        rps: float = 3.0,
        max_concurrency: int = 4,
        max_retries: int = 6,
        backoff_base_s: float = 0.35,
        backoff_cap_s: float = 6.0,
    ) -> None:
        self.urls: List[str] = [u.strip() for u in rpc_urls if u and u.strip()]
        if not self.urls:
            raise ValueError("SolanaRPCPool: rpc_urls empty")

        self.clients: List[SolanaRPCAsync] = [
            SolanaRPCAsync(
                u,
                timeout_s=timeout_s,
                rps=rps,
                max_concurrency=max_concurrency,
                max_retries=max_retries,
                backoff_base_s=backoff_base_s,
                backoff_cap_s=backoff_cap_s,
            )
            for u in self.urls
        ]
        self._idx = random.randrange(0, len(self.clients))

    def _pick_indices(self) -> List[int]:
        # start from current idx, then try all
        n = len(self.clients)
        start = self._idx % n
        order = list(range(start, n)) + list(range(0, start))
        # next call rotates start
        self._idx = (self._idx + 1) % n
        return order

    @staticmethod
    def _looks_like_transient(e: Exception) -> bool:
        if isinstance(e, RpcResponseError):
            msg = (e.message or "").lower()
            # typical transient patterns
            if "too many requests" in msg or "429" in msg:
                return True
            if "timed out" in msg or "timeout" in msg:
                return True
            if "gateway" in msg or "temporarily" in msg or "unavailable" in msg:
                return True
        return False

    async def call(self, method: str, params: list) -> Any:
        last_exc: Optional[Exception] = None
        for i in self._pick_indices():
            try:
                return await self.clients[i].call(method, params)
            except Exception as e:
                last_exc = e
                if self._looks_like_transient(e):
                    # try next endpoint
                    continue
                # non transient => raise immediately
                raise
        # all failed
        if last_exc:
            raise last_exc
        raise RuntimeError("SolanaRPCPool: unknown failure")

    async def close(self) -> None:
        await asyncio.gather(*[c.close() for c in self.clients], return_exceptions=True)

    async def aclose(self) -> None:
        await self.close()
