from __future__ import annotations
import logging
log = logging.getLogger("AntiRug")

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from core.solana_rpc_async import TOKEN_2022_PROGRAM_ID, TOKEN_PROGRAM_ID

# --- knobs (env overridable)
MAX_FALLBACK_ACCOUNTS = int(__import__("os").getenv("ANTI_RUG_FALLBACK_MAX_ACCOUNTS", "5000"))
FALLBACK_CONCURRENCY_SLEEP_S = float(__import__("os").getenv("ANTI_RUG_FALLBACK_SLEEP_S", "0.0"))


@dataclass
class RiskResult:
    ok: bool
    reason: str
    details: Optional[Dict[str, Any]] = None


class AntiRug:
    """
    On-chain checks:
      - mint account exists
      - token program owner is SPL-Token (optionally block Token-2022)
      - require renounced: mintAuthority=None AND freezeAuthority=None
      - holders concentration: top1/top10 %
        primary: getTokenLargestAccounts
        fallback on 429: getTokenAccountsByMint + aggregate owners (bounded)
    """

    def __init__(self, rpc, logger, *, block_token_2022: bool = True):
        self.rpc = rpc
        self.logger = logger
        self.block_token_2022 = bool(block_token_2022)

    # ----------------------------
    # low-level helpers
    # ----------------------------
    @staticmethod
    def _is_429(err: Any) -> bool:
        try:
            return isinstance(err, dict) and int(err.get("code", 0)) == 429
        except Exception:
            log.info("[ANTI_RUG] FAIL mint=%s", mint)
            log.info("[ANTI_RUG] FAIL mint=%s", mint)
            log.info("[ANTI_RUG] FAIL mint=%s", mint)
            log.info("[ANTI_RUG] FAIL mint=%s", mint)
            return False

    async def _call(self, method: str, params: list) -> Tuple[bool, Any, Optional[Any]]:
        """
        Returns (ok, result, error)
        ok=True  => result is JSON-RPC result
        ok=False => error is JSON-RPC error dict or exception str
        """
        try:
            res = await self.rpc.call(method, params)
            return True, res, None
        except Exception as e:
            return False, None, {"code": -1, "message": str(e)}

    # ----------------------------
    # main entry
    # ----------------------------
    async def check(
        self,
        mint: str,
        *,
        max_top1: float = 0.25,
        max_top10: float = 0.60,
        require_renounced: bool = True,
    ) -> RiskResult:
        details: Dict[str, Any] = {}

        # 1) mint account info (program owner + parsed mint authorities)
        ok, res, err = await self._call(
            "getAccountInfo",
            [mint, {"encoding": "jsonParsed"}],
        )
        if not ok:
            return RiskResult(False, f"mint introuvable (RPC)", details={"rpc_error": err})

        value = (res or {}).get("value")
        if not value:
            return RiskResult(False, "mint introuvable (RPC)", details={"rpc": "no value"})

        owner = value.get("owner")
        details["program_owner"] = owner

        if self.block_token_2022 and owner == TOKEN_2022_PROGRAM_ID:
            return RiskResult(False, "token2022 blocked", details)

        if owner != TOKEN_PROGRAM_ID and owner != TOKEN_2022_PROGRAM_ID:
            return RiskResult(False, f"unexpected mint owner {owner}", details)

        parsed = (((value.get("data") or {}).get("parsed") or {}).get("info") or {})
        mint_auth = parsed.get("mintAuthority")
        freeze_auth = parsed.get("freezeAuthority")
        decimals = parsed.get("decimals")
        supply_str = parsed.get("supply")

        details["decimals"] = decimals
        details["mint_authority"] = mint_auth
        details["freeze_authority"] = freeze_auth
        details["supply_str"] = supply_str

        if require_renounced:
            if mint_auth is not None or freeze_auth is not None:
                return RiskResult(False, "mint/freeze authority not renounced", details)

        # 2) supply (for % computation) via getTokenSupply (cheap)
        ok, sup_res, sup_err = await self._call("getTokenSupply", [mint])
        if not ok:
            return RiskResult(False, f"supply check fail: {sup_err}", details)

        sup_val = ((sup_res or {}).get("value") or {})
        supply_amount = int(sup_val.get("amount") or 0)
        supply_decimals = int(sup_val.get("decimals") or (decimals or 0))
        if supply_amount <= 0:
            # some mints show 0 (burned/invalid); reject for safety
            details["supply_amount"] = supply_amount
            details["supply_decimals"] = supply_decimals
            return RiskResult(False, "supply invalid (0)", details)

        details["supply_amount"] = supply_amount
        details["supply_decimals"] = supply_decimals

        # 3) holders check: primary then fallback
        rr = await self._holders_check(mint, supply_amount, max_top1=max_top1, max_top10=max_top10)
        rr.details = {**details, **(rr.details or {})}
        return rr

    async def _holders_check(
        self,
        mint: str,
        supply_amount: int,
        *,
        max_top1: float,
        max_top10: float,
    ) -> RiskResult:
        # --- primary: getTokenLargestAccounts
        ok, res, err = await self._call("getTokenLargestAccounts", [mint])
        if ok:
            return self._eval_largest_accounts(res, supply_amount, max_top1=max_top1, max_top10=max_top10)

        # if not ok: if 429 -> fallback bounded
        if self._is_429(err):
            self.logger and self.logger.info("[AntiRug] 429 on getTokenLargestAccounts -> fallback getTokenAccountsByMint")
            fb = await self._fallback_accounts_by_mint(mint, supply_amount, max_top1=max_top1, max_top10=max_top10)
            return fb

        return RiskResult(False, f"holders check fail: RPC error on getTokenLargestAccounts | data={err}", {"rpc_error": err})

    def _eval_largest_accounts(
        self,
        res: Any,
        supply_amount: int,
        *,
        max_top1: float,
        max_top10: float,
    ) -> RiskResult:
        vals = ((res or {}).get("value") or [])
        amounts = []
        for it in vals:
            amt = (it.get("amount") if isinstance(it, dict) else None)
            try:
                amounts.append(int(amt or 0))
            except Exception:
                amounts.append(0)

        if not amounts:
            return RiskResult(False, "holders list empty", {"holders": "empty"})

        top1 = amounts[0]
        top10 = sum(amounts[:10])

        p1 = top1 / supply_amount
        p10 = top10 / supply_amount

        det = {"top1_pct": p1, "top10_pct": p10, "source": "getTokenLargestAccounts"}

        if p1 > max_top1:
            return RiskResult(False, f"top1 too high {p1:.3f} > {max_top1:.3f}", det)
        if p10 > max_top10:
            return RiskResult(False, f"top10 too high {p10:.3f} > {max_top10:.3f}", det)

        return RiskResult(True, "ok", det)

    async def _fallback_accounts_by_mint(
        self,
        mint: str,
        supply_amount: int,
        *,
        max_top1: float,
        max_top10: float,
    ) -> RiskResult:
        # This can be heavy; we bound by MAX_FALLBACK_ACCOUNTS to avoid melting.
        ok, res, err = await self._call(
            "getTokenAccountsByMint",
            [mint, {"encoding": "jsonParsed"}],
        )
        if not ok:
            # still limited or failing
            return RiskResult(False, f"holders fallback fail: {err}", {"source": "getTokenAccountsByMint", "rpc_error": err})

        vals = ((res or {}).get("value") or [])
        n = len(vals)
        if n == 0:
            return RiskResult(False, "holders fallback empty", {"source": "getTokenAccountsByMint", "n": 0})

        if n > MAX_FALLBACK_ACCOUNTS:
            return RiskResult(False, f"holders fallback too many accounts ({n} > {MAX_FALLBACK_ACCOUNTS})", {"source": "getTokenAccountsByMint", "n": n})

        # Aggregate owner balances
        owner_amt: Dict[str, int] = {}
        for i, it in enumerate(vals):
            if FALLBACK_CONCURRENCY_SLEEP_S > 0:
                # tiny yield to reduce burst on slow envs
                if i % 200 == 0:
                    await asyncio.sleep(FALLBACK_CONCURRENCY_SLEEP_S)

            acc = (it or {}).get("account") or {}
            data = (acc.get("data") or {}).get("parsed") or {}
            info = data.get("info") or {}
            owner = info.get("owner")
            tok = info.get("tokenAmount") or {}
            amt = tok.get("amount")

            if not owner:
                continue
            try:
                a = int(amt or 0)
            except Exception:
                a = 0
            owner_amt[owner] = owner_amt.get(owner, 0) + a

        if not owner_amt:
            return RiskResult(False, "holders fallback parse empty", {"source": "getTokenAccountsByMint", "n": n})

        top = sorted(owner_amt.values(), reverse=True)
        top1 = top[0]
        top10 = sum(top[:10])

        p1 = top1 / supply_amount
        p10 = top10 / supply_amount

        det = {"top1_pct": p1, "top10_pct": p10, "source": "getTokenAccountsByMint", "n_accounts": n, "n_owners": len(owner_amt)}

        if p1 > max_top1:
            return RiskResult(False, f"top1 too high {p1:.3f} > {max_top1:.3f}", det)
        if p10 > max_top10:
            return RiskResult(False, f"top10 too high {p10:.3f} > {max_top10:.3f}", det)

        return RiskResult(True, "ok", det)
