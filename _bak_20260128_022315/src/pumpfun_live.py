import asyncio
import logging
import time

from core.pumpfun_listener import PumpfunOnChainListener
from core.candidate_pipeline import CandidatePipeline

logging.basicConfig(level=logging.INFO)


async def main():
    listener = PumpfunOnChainListener()
    pipeline = CandidatePipeline()

    logging.info("🚀 Listening pump.fun creations (CTRL+C pour arrêter)")

    async for evt in listener.listen():
        decision = pipeline.on_new_token(evt)
        age = time.time() - evt["created_ts"]

        logging.info(
            "[PUMPFUN] mint=%s dev=%s age=%.2fs decision=%s",
            evt["mint"],
            evt["creator"],
            age,
            decision,
        )


if __name__ == "__main__":
    asyncio.run(main())
