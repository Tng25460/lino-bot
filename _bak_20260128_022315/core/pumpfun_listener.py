from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncIterator, Dict, Optional

import aiohttp
from websockets import connect
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger("PumpfunListener")

# ✅ Pump.fun Program ID (création)
DEFAULT_PUMPFUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"


class PumpfunOnChainListener:
    """
    Listener on-chain Pump.fun :
    - écoute logsSubscribe(program_id)
    - récupère la tx via RPC HTTP
    - extrait mint + creator
    - dé-dup par mint
    """

    def __init__(
        self,
        rpc_ws: str = "wss://api.mainnet-beta.solana.com",
        rpc_http: str = "https://api.mainnet-beta.solana.com",
        program_id: Optional[str] = None,
        commitment: str = "confirmed",
    ):
        self.rpc_ws = rpc_ws
        self.rpc_http = rpc_http
        self.program_id = (program_id or os.getenv("PUMPFUN_PROGRAM_ID") or DEFAULT_PUMPFUN_PROGRAM_ID).strip()
        self.commitment = commitment

        self.running = False
        self._seen_mints: Dict[str, float] = {}

    def stop(self) -> None:
        self.running = False

    async def _rpc(self, session: aiohttp.ClientSession, method: str, params: list) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        async with session.post(self.rpc_http, json=payload, timeout=20) as r:
            data = await r.json(content_type=None)
            return data.get("result")

    async def _get_tx(self, session: aiohttp.ClientSession, sig: str) -> Optional[Dict[str, Any]]:
        # retry rapide pour être early
        for delay in (0.0, 0.15, 0.3, 0.5):
            if delay:
                await asyncio.sleep(delay)
            try:
                res = await self._rpc(
                    session,
                    "getTransaction",
                    [
                        sig,
                        {
                            "encoding": "jsonParsed",
                            "maxSupportedTransactionVersion": 0,
                            "commitment": self.commitment,
                        },
                    ],
                )
                if res:
                    return res
            except Exception:
                pass
        return None

    def _extract_creator(self, tx: Dict[str, Any]) -> str:
        keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
        for k in keys:
            if isinstance(k, dict) and k.get("signer"):
                return str(k.get("pubkey") or "")
        if keys and isinstance(keys[0], dict):
            return str(keys[0].get("pubkey") or "")
        if keys and isinstance(keys[0], str):
            return keys[0]
        return ""

    def _extract_mint(self, tx: Dict[str, Any]) -> str:
        meta = tx.get("meta") or {}
        pre = meta.get("preTokenBalances") or []
        post = meta.get("postTokenBalances") or []

        pre_mints = {b.get("mint") for b in pre if b.get("mint")}
        for b in post:
            m = b.get("mint")
            if m and m not in pre_mints:
                return str(m)
        return ""

    async def _enrich_event(self, session: aiohttp.ClientSession, sig: str) -> Optional[Dict[str, Any]]:
        tx = await self._get_tx(session, sig)
        if not tx:
            return None

        mint = self._extract_mint(tx)
        creator = self._extract_creator(tx)
        created_ts = tx.get("blockTime") or time.time()

        if not mint or not creator:
            return None

        now = time.time()
        last = self._seen_mints.get(mint, 0.0)
        if now - last < 45:
            return None
        self._seen_mints[mint] = now

        return {
            "mint": mint,
            "creator": creator,
            "created_ts": float(created_ts),
            "source": "pumpfun",
            "signature": sig,
        }

    async def listen(self) -> AsyncIterator[Dict[str, Any]]:
        if not self.program_id:
            raise RuntimeError("PUMPFUN program_id manquant")

        self.running = True
        logger.info("[PUMPFUN] program_id=%s", self.program_id)

        while self.running:
            try:
                async with connect(self.rpc_ws, ping_interval=15, ping_timeout=15) as ws:
                    logger.info("[PUMPFUN] WS connected: %s", self.rpc_ws)
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [self.program_id]},
                            {"commitment": self.commitment},
                        ],
                    }))

                    async with aiohttp.ClientSession() as session:
                        while self.running:
                            raw = await ws.recv()
                            msg = json.loads(raw)

                            val = (msg.get("params") or {}).get("result") or {}
                            sig = val.get("signature")
                            if not sig:
                                continue

                            evt = await self._enrich_event(session, sig)
                            if evt:
                                yield evt

            except (ConnectionClosed, asyncio.CancelledError):
                logger.warning("[PUMPFUN] WS closed, reconnect…")
                await asyncio.sleep(1.5)
            except Exception as e:
                logger.warning("[PUMPFUN] WS error -> reconnect: %s", e)
                await asyncio.sleep(1.5)

# ====== DEBUG TEMPORAIRE PUMPFUN ======
def _debug_log_creation(msg):
    try:
        logs = (
            msg.get("params", {})
               .get("result", {})
               .get("value", {})
               .get("logs", [])
        )
        for l in logs:
            if (
                "Initialize" in l
                or "initialize" in l
                or "Create" in l
                or "create" in l
            ):
                logger.warning("[PUMPFUN DEBUG LOG] %s", l)
    except Exception:
        pass
# ====== FIN DEBUG ======