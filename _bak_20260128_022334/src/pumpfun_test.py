import asyncio
import time
import logging

from core.pumpfun_listener import PumpfunListener
from core.candidate_pipeline import CandidatePipeline

logging.basicConfig(level=logging.INFO)

async def main():
    listener = PumpfunListener()
    pipe = CandidatePipeline()

    fake_events = [
        {"mint": "MINT1", "creator": "DEV_A", "created_ts": time.time(), "source": "pumpfun"},
        {"mint": "MINT2", "creator": "DEV_B", "created_ts": time.time() - 20, "source": "pumpfun"},
        {"mint": "MINT3", "creator": "DEV_C", "created_ts": time.time() - 400, "source": "pumpfun"},
    ]

    for evt in fake_events:
        decision = pipe.on_new_token(evt)
        logging.info(
            "[PUMPFUN] mint=%s dev=%s age=%.1fs decision=%s",
            evt["mint"], evt["creator"], time.time() - evt["created_ts"], decision
        )

    # on ne démarre pas listener.listen() ici (stub)
    try:
        listener.stop()
    except Exception:
        pass

if __name__ == "__main__":
    asyncio.run(main())
