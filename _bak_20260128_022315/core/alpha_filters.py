from __future__ import annotations

import os
import math
import builtins
from typing import Any, Dict, Optional

# -------------------------
# Safe helpers (évite shadowing float/int)
# -------------------------
def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, (int, float)):
            return builtins.float(x)
        s = str(x).strip()
        if s == "":
            return default
        return builtins.float(s)
    except Exception:
        return default

def safe_int(x: Any, default: int = 0) -> int:
    try:
        if x is None:
            return default
        if isinstance(x, bool):
            return default
        if isinstance(x, int):
            return x
        if isinstance(x, float):
            return int(x)
        s = str(x).strip()
        if s == "":
            return default
        return int(float(s))
    except Exception:
        return default

def getenv_float(name: str, default: float) -> float:
    return safe_float(os.getenv(name, default), default)

def getenv_int(name: str, default: int) -> int:
    return safe_int(os.getenv(name, default), default)

# -------------------------
# Extract DexScreener fields safely
# overviews: dict from TokenScanner
# -------------------------
def _get_nested(d: Dict[str, Any], *keys: str) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur

def tx_per_minute(ov: Dict[str, Any]) -> float:
    """
    DexScreener peut fournir:
      ov["data"]["txns"]["m5"]["buys"/"sells"]
      ov["data"]["txns"]["h1"]["buys"/"sells"]
    On calcule un tx/min robuste.
    """
    tx_m5 = _get_nested(ov, "data", "txns", "m5")
    if isinstance(tx_m5, dict):
        buys = safe_int(tx_m5.get("buys"))
        sells = safe_int(tx_m5.get("sells"))
        total_5m = buys + sells
        return total_5m / 5.0

    tx_h1 = _get_nested(ov, "data", "txns", "h1")
    if isinstance(tx_h1, dict):
        buys = safe_int(tx_h1.get("buys"))
        sells = safe_int(tx_h1.get("sells"))
        total_60m = buys + sells
        return total_60m / 60.0

    return 0.0

def price_change_1h_pct(ov: Dict[str, Any]) -> float:
    # DexScreener often: data.priceChange.h1
    pc = _get_nested(ov, "data", "priceChange", "h1")
    return safe_float(pc, 0.0)

def volume_1h_usd(ov: Dict[str, Any]) -> float:
    # DexScreener often: data.volume.h1
    v = _get_nested(ov, "data", "volume", "h1")
    return safe_float(v, 0.0)

def volume_24h_usd(ov: Dict[str, Any]) -> float:
    # sometimes scanner maps liquidity_usd, marketcap_usd; volume might be in ov["data"]["volume"]["h24"]
    v = _get_nested(ov, "data", "volume", "h24")
    return safe_float(v, 0.0)

def liquidity_usd(ov: Dict[str, Any]) -> float:
    return safe_float(ov.get("liquidity_usd") or _get_nested(ov, "data", "liquidity"), 0.0)

# -------------------------
# Signals
# -------------------------
def momentum_breakout(ov: Dict[str, Any]) -> bool:
    """
    Simple: breakout si priceChange.h1 >= seuil
    """
    th = getenv_float("ALPHA_MOMENTUM_H1_PCT", 8.0)  # 8% par défaut
    return price_change_1h_pct(ov) >= th

def volume_acceleration(ov: Dict[str, Any]) -> bool:
    """
    Si tu exposes un champ volumeChange (certaines APIs le font), on le prend.
    Sinon fallback: volume.h1 >= seuil.
    """
    # optional: data.volumeChange.h1
    vc = _get_nested(ov, "data", "volumeChange", "h1")
    if vc is not None:
        th = getenv_float("ALPHA_VOL_ACCEL_H1_PCT", 50.0)  # +50%
        return safe_float(vc, 0.0) >= th

    v1h = volume_1h_usd(ov)
    th_usd = getenv_float("ALPHA_MIN_VOL_1H_USD", 1500.0)
    return v1h >= th_usd

def score_overview(ov: Dict[str, Any]) -> float:
    """
    Score 0..100 (approx). Purement heuristique, safe.
    """
    liq = liquidity_usd(ov)
    v24 = volume_24h_usd(ov)
    tpm = tx_per_minute(ov)
    pc1h = price_change_1h_pct(ov)

    # Normalize with log to avoid insane ranges
    liq_s = min(40.0, 10.0 * math.log10(1.0 + max(0.0, liq)))
    v24_s = min(25.0, 8.0 * math.log10(1.0 + max(0.0, v24)))
    tpm_s = min(25.0, 12.0 * math.log10(1.0 + max(0.0, tpm)))

    mom_bonus = 10.0 if pc1h >= getenv_float("ALPHA_MOMENTUM_H1_PCT", 8.0) else 0.0
    accel_bonus = 5.0 if volume_acceleration(ov) else 0.0

    score = liq_s + v24_s + tpm_s + mom_bonus + accel_bonus
    return float(max(0.0, min(100.0, score)))

def should_skip_buy(ov: Dict[str, Any]) -> Optional[str]:
    """
    Retourne une raison (str) si on doit SKIP, sinon None.
    Tout est piloté par env vars => très safe.
    """
    if os.getenv("ENABLE_ALPHA_FILTERS", "1") not in ("1", "true", "TRUE", "yes", "YES"):
        return None

    min_liq = getenv_float("ALPHA_MIN_LIQ_USD", 2500.0)
    min_tpm = getenv_float("ALPHA_MIN_TX_PER_MIN", 2.0)     # ⚠️ important: tx/min
    min_score = getenv_float("ALPHA_MIN_SCORE", 45.0)

    liq = liquidity_usd(ov)
    tpm = tx_per_minute(ov)
    sc = score_overview(ov)

    if liq < min_liq:
        return f"LOW_LIQ liq={liq:.2f} < {min_liq:.2f}"
    if tpm < min_tpm:
        return f"LOW_TX_PER_MIN tpm={tpm:.2f} < {min_tpm:.2f}"
    if sc < min_score:
        return f"LOW_SCORE score={sc:.1f} < {min_score:.1f}"

    return None

# -------------------------
# Anti-sandwich (simple)
# -------------------------
def anti_sandwich_guard(jup_quote: Dict[str, Any]) -> Optional[str]:
    """
    Si tu as déjà un dict quote Jupiter, vérifie priceImpactPct.
    Retourne une raison si trop risqué.
    """
    if os.getenv("ENABLE_ANTI_SANDWICH", "1") not in ("1", "true", "TRUE", "yes", "YES"):
        return None
    max_pi = getenv_float("MAX_PRICE_IMPACT_PCT", 1.8)  # 1.8% défaut

    pi = jup_quote.get("priceImpactPct")
    if pi is None:
        # pas dispo => on ne bloque pas
        return None

    pi_f = safe_float(pi, 0.0)
    # certaines versions renvoient 0.0123 (1.23%) ou 1.23 (1.23%)
    if pi_f <= 0.0:
        return None
    if pi_f < 0.2:  # assume fraction (0.012 = 1.2%)
        pi_pct = pi_f * 100.0
    else:
        pi_pct = pi_f

    if pi_pct > max_pi:
        return f"HIGH_PRICE_IMPACT {pi_pct:.2f}% > {max_pi:.2f}%"

    return None
