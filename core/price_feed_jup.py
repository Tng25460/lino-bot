import asyncio
from typing import Optional

from core.jupiter_price_async import JupiterPriceV3Async


class JupPriceFeed:
    """
    Price feed sync (get_price) basé sur JupiterPriceV3Async.
    Retourne un prix float (USD) ou None.
    """
    def __init__(self):
        self._jp = JupiterPriceV3Async()

    def get_price(self, mint: str) -> Optional[float]:
        async def _get():
            return await self._jp.get_price_usd(mint)

        try:
            v = asyncio.run(_get())
            return float(v) if v else None
        except RuntimeError:
            # fallback si loop déjà actif
            loop = asyncio.get_event_loop()
            v = loop.run_until_complete(_get())
            return float(v) if v else None
        except Exception:
            return None
