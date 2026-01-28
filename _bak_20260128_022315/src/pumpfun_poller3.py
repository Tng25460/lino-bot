import asyncio
import logging
import time
from typing import Any, Dict, Optional, List

import aiohttp

log = logging.getLogger("pumpfun_poller3")

# Pump.fun Program (create)
PUMPFUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

RPC_HTTP = "https://api.mainnet-beta.solana.com"

IGNORE_MINTS = {
    # WSOL
    "So11111111111111111111111111111111111111112",
    # USDC
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    # USDT
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}


async def rpc(session: aiohttp.ClientSession, method: str, params: list) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with session.post(RPC_HTTP, json=payload, timeout=aiohttp.ClientTimeout(total=25)) as r:
        data = await r.json(content_type=None)
        if data.get("error"):
            raise RuntimeError(data["error"])
        return data.get("result")


async def get_signatures_for_address(session: aiohttp.ClientSession, address: str, limit: int = 100) -> List[dict]:
    res = await rpc(session, "getSignaturesForAddress", [address, {"limit": int(limit)}])
    return res or []


async def get_tx_with_retries(session: aiohttp.ClientSession, sig: str, commitment: str = "confirmed") -> Optional[Dict[str, Any]]:
    # getTransaction peut être NULL un moment -> retries rapides + un peu plus longs
    delays = [0.0, 0.15, 0.25, 0.35, 0.5, 0.75, 1.0, 1.5, 2.2, 3.0, 4.0]
    for d in delays:
        if d:
            await asyncio.sleep(d)
        try:
            tx = await rpc(
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
            if isinstance(tx, dict) and tx:
                return tx
        except Exception:
            pass
    return None


def extract_creator(tx: Dict[str, Any]) -> str:
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


def extract_new_mint_from_balances(tx: Dict[str, Any]) -> Optional[str]:
    meta = tx.get("meta") or {}
    pre = meta.get("preTokenBalances") or []
    post = meta.get("postTokenBalances") or []

    pre_mints = {str(b.get("mint")) for b in pre if b.get("mint")}
    for b in post:
        m = b.get("mint")
        if not m:
            continue
        ms = str(m)
        if ms not in pre_mints:
            return ms
    return None


def extract_initialize_mint(tx: Dict[str, Any]) -> Optional[str]:
    """
    Extract mint from SPL initializeMint/initializeMint2 (outer+inner).
    """
    t = tx.get("transaction") or {}
    msg = t.get("message") or {}
    meta = tx.get("meta") or {}

    def scan(instrs):
        for ix in instrs or []:
            if not isinstance(ix, dict):
                continue
            parsed = ix.get("parsed")
            if not isinstance(parsed, dict):
                continue
            typ = (parsed.get("type") or "").lower()
            if typ in ("initializemint", "initializemint2"):
                info = parsed.get("info") or {}
                m = info.get("mint")
                if m:
                    return str(m)
        return None

    m = scan(msg.get("instructions") or [])
    if m:
        return m

    inner = meta.get("innerInstructions") or []
    for bloc in inner:
        m = scan((bloc or {}).get("instructions") or [])
        if m:
            return m

    return None


def pick_mint(tx: Dict[str, Any]) -> Optional[str]:
    mint = extract_new_mint_from_balances(tx) or extract_initialize_mint(tx)
    if mint and mint not in IGNORE_MINTS:
        return mint
    return None


async def main():
    logging.basicConfig(level=logging.INFO)
    log.info("🚀 Pump.fun POLLER v3 (clean) démarré")
    log.info("   pumpfun_program=%s", PUMPFUN_PROGRAM_ID)
    log.info("   rpc_http=%s", RPC_HTTP)

    seen_sigs = set()

    # PENDING: sig -> info (on recheck plus tard pour trouver le mint)
    PENDING: Dict[str, Dict[str, Any]] = {}

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                sigs = await get_signatures_for_address(session, PUMPFUN_PROGRAM_ID, limit=120)

                # on traite du + ancien au + récent pour un ordre logique
                sigs = list(reversed(sigs))

                for item in sigs:
                    sig = item.get("signature")
                    if not sig or sig in seen_sigs:
                        continue
                    seen_sigs.add(sig)

                    block_time = item.get("blockTime")
                    created_ts = float(block_time) if block_time else time.time()

                    tx = await get_tx_with_retries(session, sig)
                    if not tx:
                        # on garde quand même en pending, parce que tx peut apparaître après
                        PENDING[sig] = {"ts": time.time(), "created_ts": created_ts, "creator": None}
                        continue

                    creator = extract_creator(tx)
                    mint = pick_mint(tx)

                    age = time.time() - created_ts
                    if mint:
                        logging.error(
                            "🔥 [PUMPFUN_MINT] mint=%s creator=%s age=%.2fs sig=%s (fast)",
                            mint, creator, age, sig
                        )
                    else:
                        # normal: souvent le mint n'est pas visible immédiatement
                        PENDING[sig] = {"ts": time.time(), "created_ts": created_ts, "creator": creator}
                        logging.warning(
                            "[PUMPFUN_CREATE] mint=None creator=%s age=%.2fs sig=%s",
                            creator, age, sig
                        )

                # --- RECHECK PENDING ---
                if PENDING:
                    logging.info("[PENDING] size=%d (recheck…)", len(PENDING))

                now = time.time()
                to_drop = []
                for psig, info in list(PENDING.items()):
                    # on abandonne après 120s
                    if now - float(info["ts"]) > 120.0:
                        to_drop.append(psig)
                        continue

                    tx2 = await get_tx_with_retries(session, psig)
                    if not tx2:
                        continue

                    mint2 = pick_mint(tx2)
                    if not mint2:
                        continue

                    creator2 = info.get("creator") or extract_creator(tx2)
                    created_ts2 = float(info.get("created_ts") or now)
                    age2 = time.time() - created_ts2

                    logging.error(
                        "🔥 [PUMPFUN_MINT] mint=%s creator=%s age=%.2fs sig=%s (late)",
                        mint2, creator2, age2, psig
                    )
                    to_drop.append(psig)

                for psig in to_drop:
                    PENDING.pop(psig, None)

            except Exception as e:
                logging.warning("[loop] error=%s", e)

            await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
