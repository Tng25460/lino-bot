import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional, List

import aiohttp

from core.pumpfun_tracker import PumpfunTracker

# Pump.fun Program (creations)
PUMPFUN_PROGRAM_ID = os.getenv("PUMPFUN_PROGRAM_ID", "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")

RPC_HTTP = os.getenv("SOLANA_RPC_HTTP", "https://api.mainnet-beta.solana.com")

LOG = logging.getLogger("pumpfun_poller2")

IGNORE_MINTS = {
    # WSOL
    "So11111111111111111111111111111111111111112",
    # USDC main
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    # USDT main
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}


async def rpc(session: aiohttp.ClientSession, method: str, params: list) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with session.post(RPC_HTTP, json=payload, timeout=aiohttp.ClientTimeout(total=25)) as r:
        data = await r.json(content_type=None)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(data["error"])
        return data.get("result")


def _extract_creator_from_tx(tx: Dict[str, Any]) -> str:
    # feePayer / first signer heuristic
    t = tx.get("transaction") or {}
    msg = t.get("message") or {}
    keys = msg.get("accountKeys") or []
    for k in keys:
        if isinstance(k, dict) and k.get("signer"):
            return str(k.get("pubkey") or "")
    if keys and isinstance(keys[0], dict):
        return str(keys[0].get("pubkey") or "")
    if keys and isinstance(keys[0], str):
        return str(keys[0])
    return ""


def _scan_initialize_mint(instrs: List[Dict[str, Any]]) -> Optional[str]:
    for ix in instrs or []:
        if not isinstance(ix, dict):
            continue
        parsed = ix.get("parsed")
        if not isinstance(parsed, dict):
            continue
        typ = (parsed.get("type") or "").lower()
        if typ in ("initializemint", "initializemint2"):
            info = parsed.get("info") or {}
            mint = info.get("mint")
            if mint:
                return str(mint)
    return None


def extract_spl_mint_from_tx(tx: Dict[str, Any]) -> Optional[str]:
    """
    Prefer SPL-Token initializeMint/initializeMint2 (outer + inner).
    Much less false positives than reading token balances.
    """
    if not isinstance(tx, dict):
        return None

    t = tx.get("transaction") or {}
    msg = t.get("message") or {}
    meta = tx.get("meta") or {}

    # outer
    mint = _scan_initialize_mint(msg.get("instructions") or [])
    if mint:
        return mint

    # inner
    inner = meta.get("innerInstructions") or []
    for blk in inner:
        if not isinstance(blk, dict):
            continue
        mint = _scan_initialize_mint(blk.get("instructions") or [])
        if mint:
            return mint

    return None


async def get_tx_with_retries(session: aiohttp.ClientSession, sig: str, commitment: str = "confirmed") -> Optional[Dict[str, Any]]:
    # getTransaction can be null briefly -> retry quickly
    delays = [0.0, 0.15, 0.25, 0.35, 0.5, 0.75]
    for d in delays:
        if d:
            await asyncio.sleep(d)
        try:
            res = await rpc(
                session,
                "getTransaction",
                [
                    sig,
                    {
                        "encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0,
                        "commitment": commitment,
                    },
                ],
            )
            if isinstance(res, dict) and res:
                return res
        except Exception:
            pass
    return None


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    LOG.info("🚀 Pump.fun POLLER v2 (creator->WAIT_MINT->ARMED) démarré")
    LOG.info("   program=%s", PUMPFUN_PROGRAM_ID)

    tracker = PumpfunTracker()

    seen_sigs = set()
    last_before = None  # pagination cursor

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # Pull latest signatures mentioning Pump.fun program (address)
                params = [PUMPFUN_PROGRAM_ID, {"limit": 50}]
                if last_before:
                    params[1]["before"] = last_before

                sigs = await rpc(session, "getSignaturesForAddress", params)
                if not isinstance(sigs, list) or not sigs:
                    await asyncio.sleep(0.6)
                    last_before = None
                    continue

                # Process oldest -> newest
                sigs = list(reversed(sigs))

                # update cursor to paginate older if needed, but we usually want realtime:
                # so we set cursor to the newest sig we saw, and reset often.
                newest_sig = sigs[-1].get("signature")
                last_before = None  # realtime mode

                for item in sigs:
                    sig = item.get("signature")
                    if not sig or sig in seen_sigs:
                        continue
                    seen_sigs.add(sig)
                    if len(seen_sigs) > 4000:
                        # simple memory bound
                        seen_sigs = set(list(seen_sigs)[-2000:])

                    block_time = item.get("blockTime") or 0
                    created_ts = float(block_time) if block_time else time.time()

                    tx = await get_tx_with_retries(session, sig)
                    if not tx:
                        continue

                    creator = _extract_creator_from_tx(tx) or ""
                    mint = extract_spl_mint_from_tx(tx)

                    evt = {
                        "signature": sig,
                        "creator": creator,
                        "mint": mint,
                        "created_ts": created_ts,
                        "source": "pumpfun",
                    }

                    # Decision based on creator tracking (even if mint not yet found)
                    decision = tracker.on_create(evt)

                    age = (time.time() - created_ts) if created_ts else 0.0
                    logging.warning(
                        "[PUMPFUN_CREATE] mint=%s creator=%s age=%.2fs decision=%s sig=%s",
                        mint, creator, age, decision, sig
                    )

                    # If we found a mint, protect against obvious false positives
                    if mint and mint not in IGNORE_MINTS:
                        logging.error(
                            "🔥 [MINT_FOUND] mint=%s creator=%s age=%.2fs mint_sig=%s",
                            mint, creator, age, sig
                        )

                # small sleep to avoid hammering RPC
                await asyncio.sleep(0.35)

            except KeyboardInterrupt:
                LOG.info("⛔ stopped")
                return
            except Exception as e:
                LOG.warning("WS/RPC error -> retry: %s", e)
                await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
