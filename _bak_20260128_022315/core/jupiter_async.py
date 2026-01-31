from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import aiohttp


@dataclass
class JupiterError(Exception):
    message: str
    data: Any = None

    def __str__(self) -> str:
        if self.data is None:
            return self.message
        return f"{self.message} | data={self.data}"


class JupiterAsync:
    """
    Minimal async client for Jupiter API (quote/swap).
    Designed to be used by executors / price / routing.

    Env compat (optional):
      JUP_BASE or JUPITER_BASE_URL   default: https://api.jup.ag
      JUP_API_KEY or JUPITER_API_KEY
    """

    def __init__(
        self,
        base_url: str = "https://api.jup.ag",
        *,
        api_key: str = "",
        timeout_s: float = 20.0,
        rps: float = 5.0,
        max_concurrency: int = 8,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self.base_url = (base_url or "https://api.jup.ag").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.timeout_s = float(timeout_s)

        self.rps = float(max(0.0, rps))
        self._min_interval = 0.0 if self.rps <= 0 else (1.0 / self.rps)
        self._last_call_ts = 0.0
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(int(max(1, max_concurrency)))

        self._external_session = session
        self._session: Optional[aiohttp.ClientSession] = session

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self.timeout_s)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session is not None and self._external_session is None:
            await self._session.close()
        self._session = None

    def _headers(self) -> Dict[str, str]:
        h = {"accept": "application/json"}
        if self.api_key:
            h["x-api-key"] = self.api_key
        return h

    async def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._lock:
            now = time.time()
            wait = (self._last_call_ts + self._min_interval) - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_ts = time.time()

    async def _get_json(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        await self._throttle()
        async with self._sem:
            s = await self._ensure_session()
            url = f"{self.base_url}{path}"
            try:
                async with s.get(url, params=params or {}, headers=self._headers()) as resp:
                    txt = await resp.text()
                    if resp.status != 200:
                        raise JupiterError(f"Jupiter HTTP {resp.status}", txt[:400])
                    return json.loads(txt)
            except asyncio.TimeoutError as e:
                raise JupiterError("Jupiter timeout") from e
            except aiohttp.ClientError as e:
                raise JupiterError("Jupiter client error", str(e)) from e
            except json.JSONDecodeError as e:
                raise JupiterError("Jupiter invalid JSON") from e

    async def _post_json(self, path: str, *, payload: Dict[str, Any]) -> Any:
        await self._throttle()
        async with self._sem:
            s = await self._ensure_session()
            url = f"{self.base_url}{path}"
            headers = {"content-type": "application/json", **self._headers()}
            try:
                async with s.post(url, json=payload, headers=headers) as resp:
                    txt = await resp.text()
                    if resp.status != 200:
                        raise JupiterError(f"Jupiter HTTP {resp.status}", txt[:400])
                    return json.loads(txt)
            except asyncio.TimeoutError as e:
                raise JupiterError("Jupiter timeout") from e
            except aiohttp.ClientError as e:
                raise JupiterError("Jupiter client error", str(e)) from e
            except json.JSONDecodeError as e:
                raise JupiterError("Jupiter invalid JSON") from e

    async def quote(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 100,
        only_direct_routes: bool = False,
        max_accounts: Optional[int] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(int(amount)),
            "slippageBps": str(int(slippage_bps)),
            "onlyDirectRoutes": "true" if only_direct_routes else "false",
        }
        if max_accounts is not None:
            params["maxAccounts"] = str(int(max_accounts))
        j = await self._get_json("/swap/v1/quote", params=params)
        if not isinstance(j, dict):
            raise JupiterError("quote: unexpected response type", j)
        return j

    async def swap(
        self,
        *,
        quote_response: Dict[str, Any],
        user_public_key: str,
        wrap_and_unwrap_sol: bool = True,
        dynamic_compute_unit_limit: bool = True,
        prioritization_fee_lamports: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "quoteResponse": quote_response,
            "userPublicKey": user_public_key,
            "wrapAndUnwrapSol": bool(wrap_and_unwrap_sol),
            "dynamicComputeUnitLimit": bool(dynamic_compute_unit_limit),
        }
        if prioritization_fee_lamports is not None:
            payload["prioritizationFeeLamports"] = int(prioritization_fee_lamports)

        j = await self._post_json("/swap/v1/swap", payload=payload)
        if not isinstance(j, dict):
            raise JupiterError("swap: unexpected response type", j)
        return j
