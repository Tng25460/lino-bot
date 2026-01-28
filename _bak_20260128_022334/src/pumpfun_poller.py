import asyncio
import time
import logging
import aiohttp

PUMPFUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
RPC = "https://api.mainnet-beta.solana.com"

logging.basicConfig(level=logging.INFO)

async def rpc(session, method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with session.post(RPC, json=payload) as r:
        return (await r.json()).get("result")

async def main():
    seen = set()

    async with aiohttp.ClientSession() as session:
        logging.info("🚀 Pump.fun POLLER démarré")

        while True:
            sigs = await rpc(
                session,
                "getSignaturesForAddress",
                [PUMPFUN_PROGRAM_ID, {"limit": 20}],
            )

            for s in sigs or []:
                sig = s["signature"]
                if sig in seen:
                    continue
                seen.add(sig)

                tx = await rpc(
                    session,
                    "getTransaction",
                    [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
                )

                if not tx:
                    continue

                msg = tx["transaction"]["message"]
                keys = msg["accountKeys"]

                # heuristique simple : mint souvent nouveau compte writable
                writable = [
                    k["pubkey"]
                    for k in keys
                    if isinstance(k, dict) and k.get("writable")
                ]

                creator = keys[0]["pubkey"] if isinstance(keys[0], dict) else keys[0]

                logging.warning(
                    "[PUMPFUN CREATE] sig=%s creator=%s candidates=%s",
                    sig,
                    creator,
                    writable[:3],
                )

            await asyncio.sleep(1.2)

if __name__ == "__main__":
    asyncio.run(main())
