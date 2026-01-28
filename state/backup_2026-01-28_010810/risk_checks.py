from __future__ import annotations

from typing import Any, Dict, Tuple

from config.settings import MIN_LIQUIDITY_USD, MAX_MARKET_CAP_USD


class RiskChecker:
    """Risk checker compatible DexScreener + anciens formats."""

    def allow_buy(self, ov: Dict[str, Any]) -> Tuple[bool, str]:
        data = ov.get("data") or {}

        # 1) DexScreener normalized keys
        liq = ov.get("liquidity_usd")
        mc = ov.get("marketcap_usd")

        # 2) fallback old keys
        if liq is None:
            liq = data.get("liquidity")
        if mc is None:
            mc = data.get("marketCap")

        try:
            liq_f = float(liq or 0.0)
        except Exception:
            liq_f = 0.0

        try:
            mc_f = float(mc or 0.0)
        except Exception:
            mc_f = 0.0

        if liq_f < float(MIN_LIQUIDITY_USD):
            return False, f"liquidity trop faible ({liq_f:.0f} < {float(MIN_LIQUIDITY_USD):.0f})"

        if mc_f > 0 and mc_f > float(MAX_MARKET_CAP_USD):
            return False, f"marketcap trop élevé ({mc_f:.0f} > {float(MAX_MARKET_CAP_USD):.0f})"

        return True, "ok"
