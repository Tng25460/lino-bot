import asyncio
import time
import logging
from typing import AsyncIterator, Dict, Any

from solana.rpc.websocket_api import connect

logger = logging.getLogger("PumpfunOnChain")

# ⚠️ Program ID pump.fun (à vérifier/mettre à jour si besoin)
PUMPFUN_PROGRAM_ID = "pumppp...REPLACE_ME"

class PumpfunOnChainListener:
    def __init__(self, rpc_ws: str):
        self.rpc_ws = rpc_ws
        self.running = False

    async def listen(self) -> AsyncIterator[Dict[str, Any]]:
        self.running = True
        async with connect(self.rpc_ws) as ws:
            logger.info("[PUMPFUN] Listening on-chain…")
            await ws.logs_subscribe(
                filter_={"mentions": [PUMPFUN_PROGRAM_ID]},
                commitment="confirmed"
            )

            while self.running:
                msg = await ws.recv()
                value = msg.result.value

                # Ici on filtrera CreateToken / Initialize
                evt = {
                    "mint": "TO_PARSE",
                    "creator": "TO_PARSE",
                    "created_ts": time.time(),
                    "source": "pumpfun"
                }

                yield evt

    def stop(self):
        self.running = False
