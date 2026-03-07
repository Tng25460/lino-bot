from __future__ import annotations
from typing import Dict, Tuple
import os
import time

class PriceSanity:
    def __init__(self):
        self.last_good: Dict[str, float] = {}
        self.last_ts: Dict[str, int] = {}
        self.max_jump_mult = float(os.getenv("SANITY_MAX_JUMP_MULT", "6.0"))

    def filter(self, mint: str, raw_price: float) -> Tuple[bool, float, str]:
        now = int(time.time())
        if raw_price <= 0:
            return False, self.last_good.get(mint, 0.0), "raw_nonpositive"

        prev = self.last_good.get(mint)
        if not prev or prev <= 0:
            self.last_good[mint] = raw_price
            self.last_ts[mint] = now
            return True, raw_price, "init_ok"

        if raw_price > prev * self.max_jump_mult or raw_price < prev / self.max_jump_mult:
            return False, prev, "jump_reject"

        self.last_good[mint] = raw_price
        self.last_ts[mint] = now
        return True, raw_price, "ok"
