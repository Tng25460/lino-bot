from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Tuple, List


@dataclass
class TokenMetrics:
    liquidity_usd: float = 0.0
    volume_m5_usd: float = 0.0
    txns_m5: int = 0
    price_change_m5: float = 0.0
    price_change_h1: float = 0.0
    marketcap_usd: float = 0.0


def _get(d: Dict[str, Any], path: str, default=0.0):
    cur: Any = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur if cur is not None else default


def extract_metrics(ov: Dict[str, Any]) -> TokenMetrics:
    liq = float(_get(ov, "liquidity.usd", 0.0))
    vol_m5 = float(_get(ov, "volume.m5", 0.0))
    buys = int(_get(ov, "txns.m5.buys", 0) or 0)
    sells = int(_get(ov, "txns.m5.sells", 0) or 0)
    txns = buys + sells
    pc_m5 = float(_get(ov, "priceChange.m5", 0.0))
    pc_h1 = float(_get(ov, "priceChange.h1", 0.0))
    mcap = float(_get(ov, "marketCap", 0.0))
    return TokenMetrics(
        liquidity_usd=liq,
        volume_m5_usd=vol_m5,
        txns_m5=txns,
        price_change_m5=pc_m5,
        price_change_h1=pc_h1,
        marketcap_usd=mcap,
    )


def passes_quality(m: TokenMetrics, cfg) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if m.liquidity_usd < float(getattr(cfg, "MIN_LIQUIDITY_USD", 5000)):
        reasons.append("liq_low")
    if m.volume_m5_usd < float(getattr(cfg, "MIN_VOLUME_M5_USD", 2000)):
        reasons.append("vol_low")
    if m.txns_m5 < int(getattr(cfg, "MIN_TXNS_M5", 20)):
        reasons.append("txns_low")
    if m.marketcap_usd and m.marketcap_usd < float(getattr(cfg, "MIN_MARKETCAP_USD", 20000)):
        reasons.append("mcap_low")
    ok = len(reasons) == 0
    return ok, reasons


def score_token(m: TokenMetrics) -> float:
    """
    Score simple et robuste:
    - récompense liquidité, volume récent, txns
    - momentum (priceChange m5/h1) donne un bonus
    """
    # base
    score = 0.0

    # liquidité (capée)
    score += min(m.liquidity_usd / 1000.0, 30.0)          # 0..30

    # volume m5 (capé)
    score += min(m.volume_m5_usd / 500.0, 30.0)           # 0..30

    # transactions (tx/min approx = txns_m5/5)
    score += min(m.txns_m5 * 0.8, 25.0)                   # 0..25

    # momentum (m5 et h1)
    score += max(min(m.price_change_m5, 20.0), -20.0) * 0.5   # -10..+10
    score += max(min(m.price_change_h1, 30.0), -30.0) * 0.2   # -6..+6

    return float(score)


def rank_and_filter(overviews: List[Dict[str, Any]], cfg) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ov in overviews:
        m = extract_metrics(ov)
        ok, reasons = passes_quality(m, cfg)
        s = score_token(m)
        ov["_quality"] = {
            "score": s,
            "liquidity_usd": m.liquidity_usd,
            "volume_m5_usd": m.volume_m5_usd,
            "txns_m5": m.txns_m5,
            "tx_per_min": (m.txns_m5 / 5.0) if m.txns_m5 else 0.0,
            "price_change_m5": m.price_change_m5,
            "price_change_h1": m.price_change_h1,
            "marketcap_usd": m.marketcap_usd,
            "ok": ok,
            "reasons": reasons,
        }
        # filtre strict
        if ok and s >= float(getattr(cfg, "MIN_SCORE_TO_BUY", 35.0)):
            out.append(ov)

    # tri par score décroissant
    out.sort(key=lambda x: float(x.get("_quality", {}).get("score", 0.0)), reverse=True)

    # limiter le nombre de candidats -> économise les calls Jupiter
    maxn = int(getattr(cfg, "MAX_CANDIDATES_PER_LOOP", 5))
    return out[:maxn]
