from __future__ import annotations

from typing import Any, Dict


class PaperExecutor:
    def __init__(self, wallet, logger):
        self.wallet = wallet
        self.logger = logger

    async def buy(self, mint: str, sol_amount: float, price: float) -> Dict[str, Any]:
        self.logger.info("[PAPER BUY] mint=%s sol=%s price=%s", mint, sol_amount, price)
        return {"tx": f"paper_buy_{mint}"}

    async def sell(self, mint: str, pct: float = 1.0) -> Dict[str, Any]:
        self.logger.info("[PAPER SELL] mint=%s (sell all)", mint)
        return {"tx": f"paper_sell_{mint}"}
