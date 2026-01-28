from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class Fill:
    ok: bool
    price: float
    reason: str = ""

class Executor:
    def buy(self, mint: str, price: float, sol_amount: float) -> Fill:
        raise NotImplementedError

    def sell(self, mint: str, price: float, reason: str) -> Fill:
        raise NotImplementedError

class PaperExecutor(Executor):
    """
    Exécution PAPER simple : on remplit au prix donné.
    Les soldes sont gérés par TradingEngine (cash_paper).
    """
    def buy(self, mint: str, price: float, sol_amount: float) -> Fill:
        return Fill(ok=True, price=price, reason="paper_fill")

    def sell(self, mint: str, price: float, reason: str) -> Fill:
        return Fill(ok=True, price=price, reason=reason)

class RealStubExecutor(Executor):
    """
    Stub REAL : laisse en warning.
    Branchable plus tard sans casser l'engine.
    """
    def __init__(self, logger: Any):
        self.logger = logger

    def buy(self, mint: str, price: float, sol_amount: float) -> Fill:
        self.logger.warning(f"[REAL BUY STUB] would buy {mint} {sol_amount} SOL @ {price}")
        return Fill(ok=False, price=price, reason="real_stub")

    def sell(self, mint: str, price: float, reason: str) -> Fill:
        self.logger.warning(f"[REAL SELL STUB] would sell {mint} @ {price} reason={reason}")
        return Fill(ok=False, price=price, reason="real_stub")
