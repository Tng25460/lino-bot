from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger("PumpfunMintResolver")


def _extract_new_mints_from_tx(tx: Dict[str, Any]) -> List[str]:
    """
    Heuristique:
    - mint SPL apparaît souvent dans postTokenBalances
    - on cherche un mint présent en post mais pas en pre
    - on priorise ceux qui finissent par "pump" (souvent le cas)
    """
    meta = tx.get("meta") or {}
    pre = meta.get("preTokenBalances") or []
    post = meta.get("postTokenBalances") or []

    pre_mints = set()
    for b in pre:
        m = b.get("mint")
        if m:
            pre_mints.add(str(m))

    candidates: List[str] = []
    for b in post:
        m = b.get("mint")
        if not m:
            continue
        ms = str(m)
        if ms in pre_mints:
            continue
        candidates.append(ms)

    # Priorité: mints se terminant par "pump"
    pump = [m for m in candidates if m.lower().endswith("pump")]
    rest = [m for m in candidates if m not in pump]

    # dédupe en gardant l'ordre
    out: List[str] = []
    for m in pump + rest:
        if m not in out:
            out.append(m)
    return out


class MintResolver:
    def __init__(self, rpc_http: str = "https://api.mainnet-beta.solana.com", commitment: str = "confirmed"):
        self.rpc_http = rpc_http
        self.commitment = commitment

    async def _rpc(self, session: aiohttp.ClientSession, method: str, params: list) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        async with session.post(self.rpc_http, json=payload, timeout=aiohttp.ClientTimeout(total=25)) as r:
            data = await r.json(content_type=None)
            if "error" in data and data["error"]:
                raise RuntimeError(data["error"])
            return data.get("result")

    async def _get_tx_retry(self, session: aiohttp.ClientSession, sig: str) -> Optional[Dict[str, Any]]:
        delays = [0.0, 0.15, 0.25, 0.35, 0.5, 0.75, 1.0]
        for d in delays:
            if d:
                await asyncio.sleep(d)
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
                if isinstance(res, dict) and res:
                    return res
            except Exception:
                pass
        return None

    async def find_mint_for_creator(self, creator: str, lookback_limit: int = 25) -> Tuple[Optional[str], Optional[str]]:
        """
        Scan les dernières tx du creator.
        Retourne (mint, sig) dès qu'un mint SPL "nouveau" apparaît.
        """
        creator = str(creator).strip()
        if not creator:
            return None, None

        async with aiohttp.ClientSession() as session:
            try:
                sigs = await self._rpc(
                    session,
                    "getSignaturesForAddress",
                    [creator, {"limit": int(lookback_limit)}],
                )
            except Exception as e:
                logger.debug("getSignaturesForAddress fail creator=%s err=%s", creator, e)
                return None, None

            if not isinstance(sigs, list):
                return None, None

            # on parcourt du + récent au + ancien
            for s in sigs:
                sig = (s or {}).get("signature")
                if not sig:
                    continue
                tx = await self._get_tx_retry(session, sig)
                if not tx:
                    continue
                mints = _extract_new_mints_from_tx(tx)
                if mints:
                    return mints[0], sig

        return None, None
