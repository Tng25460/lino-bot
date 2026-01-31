from __future__ import annotations

import json

# ---- Bot Lino: blacklist policy ----
def _ttl_until(reason: str, normal_until: int, transient_until: int) -> int:
    return transient_until if _is_transient_reason(reason) else normal_until

def _is_transient_reason(reason: str) -> bool:
    r = (reason or "").lower()
    transient_keys = [
        "429",
        "too many requests",
        "rpc error",
        "timeout",
        "timed out",
        "temporar",
        "connection",
        "rate limit",
        "ratelimit",
        "busy",
        "unavailable",
    ]
    return any(k in r for k in transient_keys)
import os
import time
from pathlib import Path
from typing import Any, Dict, Tuple, Optional

from config import settings
from core.anti_rug import AntiRug
from core.dev_profiler import DevProfiler
from core.rpc_factory import build_rpc

# -----------------------------
# BLACKLIST FILES
# -----------------------------
BLACKLIST_DEV_PATH = Path(os.getenv("BLACKLIST_DEV_PATH", "state/blacklist_dev.json"))
BLACKLIST_MINT_PATH = Path(os.getenv("BLACKLIST_MINT_PATH", "state/blacklist_mint.json"))

# -----------------------------
# RPC SINGLETON
# -----------------------------
_RPC = None
_RPC_KIND = None

def get_rpc(logger=None):
    global _RPC, _RPC_KIND
    if _RPC is None:
        _RPC, _RPC_KIND = build_rpc()
        try:
            if logger:
                urls = getattr(_RPC, "urls", None)
                u = ",".join(urls) if urls else getattr(_RPC, "rpc_url", "")
                logger.info(f"[RPC] initialized kind={_RPC_KIND} urls={u}")
        except Exception:
            pass
    return _RPC


# -----------------------------
# UTILS
# -----------------------------
def _load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _save_json(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


# -----------------------------
# RISK CHECKER
# -----------------------------
class RiskChecker:
    """
    Central BUY gate.
    Combines:
      - liquidity / marketcap filters
      - dev blacklist
      - mint blacklist
      - AntiRug on-chain (RPC pool safe)
    """

    def __init__(self, logger, rpc_url: Optional[str] = None, mode: str = "PAPER"):
        self.logger = logger
        self.mode = (mode or "PAPER").upper()

        self.rpc = get_rpc(logger)
        self.anti = AntiRug(
            self.rpc,
            logger,
            block_token_2022=True,
        )

        self.dev_profiler = DevProfiler()

        self.bl_dev = _load_json(BLACKLIST_DEV_PATH, {})
        self.bl_mint = _load_json(BLACKLIST_MINT_PATH, {})

    # -------------------------
    # BLACKLIST HELPERS
    # -------------------------
    def _mint_blacklisted(self, mint: str) -> Optional[str]:
        rec = self.bl_mint.get(mint)
        if not rec:
            return None
        until = _ttl_until(reason, int(rec.get("until") or 0), int(__import__('time').time()) + 60)
        if until > int(time.time()):
            return str(rec.get("reason") or "BLACKLISTED")
        self.bl_mint.pop(mint, None)
        _save_json(BLACKLIST_MINT_PATH, self.bl_mint)
        return None

    def _blacklist_mint(self, mint: str, reason: str, ttl: int = 600):
        self.bl_mint[mint] = {
            "reason": reason,
            "until": int(time.time()) + int(ttl),
        }
        _save_json(BLACKLIST_MINT_PATH, self.bl_mint)

    # -------------------------
    # MAIN ENTRY
    # -------------------------
    async def allow_buy(self, ov: Dict[str, Any]) -> Tuple[bool, str]:
        mint = str(ov.get("mint") or ov.get("token") or "")
        if not mint:
            return False, "no mint"

        # mint blacklist
        r = self._mint_blacklisted(mint)
        if r:
            return False, f"mint blacklisted: {r}"

        # dev check
        dev = (ov.get("creator") or "").strip()
        if dev:
            if not self.dev_profiler.allow(dev):
                return False, "dev blacklisted"

        # liquidity / mc
        liq = float(ov.get("liquidity_usd") or 0)
        mc = float(ov.get("marketcap_usd") or 0)

        if liq < float(settings.MIN_LIQUIDITY_USD):
            return False, f"low liquidity {liq:.0f}"

        if mc > 0 and mc > float(settings.MAX_MARKET_CAP_USD):
            return False, f"mc too high {mc:.0f}"

        # PAPER: skip on-chain
        if self.mode != "REAL":
            return True, "ok(paper)"

        # -------------------------
        # ANTI RUG (ON-CHAIN)
        # -------------------------
        try:
            res = await self.anti.check(
                mint,
                max_top1=float(getattr(settings, "MAX_TOP1_PCT", 0.25)),
                max_top10=float(getattr(settings, "MAX_TOP10_PCT", 0.60)),
                require_renounced=True,
            )
        except Exception as e:
            self._blacklist_mint(mint, "ANTI_RUG_EXCEPTION", ttl=300)
            return False, f"anti_rug exception: {e}"

        if not res.ok:
            # 429 safety → temporary cooldown only
            if "Too many requests" in res.reason or "429" in res.reason:
                self._blacklist_mint(mint, "RPC_429", ttl=180)
                return False, "rpc limited (cooldown)"

            self._blacklist_mint(mint, "RISK_REJECT", ttl=1800)
            return False, res.reason

        return True, "ok"
