import os
from dataclasses import dataclass
from typing import Dict, Any, Tuple

LAMPORTS_PER_SOL = 1_000_000_000

def _f(name, d): 
    try: return float(os.getenv(name, d))
    except: return float(d)

def _i(name, d):
    try: return int(os.getenv(name, d))
    except: return int(d)

@dataclass(frozen=True)
class Strategy:
    max_trade_sol: float
    max_pct_balance: float
    fee_buffer_sol: float
    max_price_impact_pct: float
    slippage_bps: int

    @classmethod
    def from_env(cls):
        return cls(
            max_trade_sol=_f("STRAT_MAX_TRADE_SOL","0.02"),
            max_pct_balance=_f("STRAT_MAX_PCT_BALANCE","0.18"),
            fee_buffer_sol=_f("STRAT_FEE_BUFFER_SOL","0.03"),
            max_price_impact_pct=_f("TRADER_MAX_PRICE_IMPACT_PCT","1.5"),
            slippage_bps=_i("TRADER_SLIPPAGE_BPS","120"),
        )

    def trade_lamports(self, wallet_lamports: int) -> Tuple[int,str]:
        buf = int(self.fee_buffer_sol * LAMPORTS_PER_SOL)
        if wallet_lamports <= buf: 
            return 0,"buffer"
        by_pct = int(wallet_lamports * self.max_pct_balance)
        by_cap = int(self.max_trade_sol * LAMPORTS_PER_SOL)
        amt = min(by_pct, by_cap)
        if wallet_lamports - amt < buf:
            amt = max(0, wallet_lamports - buf)
        return (amt,"ok") if amt>0 else (0,"zero")

    def quote_ok(self, q: Dict[str,Any]):
        pi = float(q.get("priceImpactPct",0))
        if pi*100 > self.max_price_impact_pct:
            return False,"impact"
        return True,"ok"

    def pick_amount_lamports(self, balance_lamports: int):
        """
        Choisit un montant SOL sécurisé en lamports
        """
        sol = balance_lamports / 1e9

        # max par trade
        trade_sol = min(
            self.max_trade_sol,
            sol * self.max_pct_balance
        )

        # buffer fees
        trade_sol = trade_sol - self.fee_buffer_sol
        if trade_sol <= 0:
            return 0, "INSUFFICIENT_BALANCE_AFTER_FEES"

        lamports = int(trade_sol * 1e9)
        return lamports, "OK"
