from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import math
import os

@dataclass
class Candidate:
    mint: str
    item: Dict[str, Any]
    score_total: float

def _f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x

def _log1p_norm(x: float, scale: float) -> float:
    if x <= 0:
        return 0.0
    return _clamp(math.log1p(x) / math.log1p(scale), 0.0, 1.0)

def score_ready_items(
    ready: List[Dict[str, Any]],
    *,
    top_k: int = 60,
    deny_mints: Optional[set] = None,
) -> List[Candidate]:
    deny_mints = deny_mints or set()
    out: List[Candidate] = []

    for it in ready:
        mint = (it.get("mint") or it.get("output_mint") or "").strip()
        if not mint or mint in deny_mints:
            continue

        chg5 = _f(it.get("price_chg_5m", it.get("chg_5m", it.get("momo_5m", 0.0))))
        chg15 = _f(it.get("price_chg_15m", it.get("chg_15m", it.get("momo_15m", 0.0))))
        vol5 = _f(it.get("volume_5m_usd", it.get("vol_5m_usd", it.get("vol5", 0.0))))
        tx5 = _f(it.get("tx_5m", it.get("txns_5m", it.get("tx5", 0.0))))
        impact = _f(it.get("price_impact_pct", it.get("impact_pct", 0.0)))

        score_momo = _clamp((chg5 * 0.6 + chg15 * 0.4) / 20.0, 0.0, 1.0)
        score_vol = _log1p_norm(vol5, float(os.getenv("VNEXT_VOL_SCALE", "50000")))
        score_tx = _log1p_norm(tx5, float(os.getenv("VNEXT_TX_SCALE", "250")))
        penalty = _clamp((impact - 4.0) / 10.0, 0.0, 0.5)

        total = 0.40 * score_momo + 0.30 * score_vol + 0.20 * score_tx - 0.20 * penalty
        out.append(Candidate(mint=mint, item=it, score_total=total))

    out.sort(key=lambda c: c.score_total, reverse=True)
    return out[:max(1, top_k)]

def size_from_score(score_total: float) -> float:
    lo = float(os.getenv("VNEXT_SIZE_MIN_MULT", "0.70"))
    hi = float(os.getenv("VNEXT_SIZE_MAX_MULT", "1.20"))
    x = _clamp(score_total, 0.0, 1.0)
    return lo + (hi - lo) * (x ** 1.5)
