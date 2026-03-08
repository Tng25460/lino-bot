"""
PHASE4_P4.6: Sizing Advisor — taille de position dynamique.

Ajuste la taille du BUY en fonction de:
  1. Score elite (0-100) → multiplicateur score
  2. Regime marche → multiplicateur regime
  3. Risk state → sizing_multiplier depuis risk_engine (pertes consecutives)

Sortie:
  {
    "recommended_sol": float,
    "base_sol": float,
    "score_mult": float,
    "regime_mult": float,
    "risk_mult": float,
    "final_mult": float,
    "clamped": bool,
    "reason": str
  }

Bornes:
  MIN_BUY_SOL    — plancher (defaut 0.005 SOL)
  MAX_BUY_SOL    — plafond (defaut 0.1 SOL)
  MAX_EXPOSURE   — exposition totale max (defaut 0.5 SOL)

Integration:
  trader_exec.py → apres circuit_breaker, avant QUOTE
  Modifie amount_lamports si sizing est actif (SIZING_ENABLED=1)

Fail-open: si erreur → retourne le montant de base inchange.
"""
from __future__ import annotations
import os
import time
from typing import Any, Dict


# ============================================================
# Configuration (env-overridable)
# ============================================================
def _fenv(name: str, default: float) -> float:
    try:
        v = os.getenv(name, "")
        return float(v) if v.strip() else float(default)
    except Exception:
        return float(default)


# ============================================================
# Score multiplier
# ============================================================
def _score_multiplier(score_total: float) -> float:
    """
    Multiplicateur base sur le score elite (0-100).

    score < 30  → 0.5  (tres prudent)
    30-40       → 0.7
    40-55       → 1.0  (normal)
    55-70       → 1.2
    70-85       → 1.5
    85+         → 1.8  (haute conviction)
    """
    if score_total < 30:
        return 0.5
    elif score_total < 40:
        return 0.7
    elif score_total < 55:
        return 1.0
    elif score_total < 70:
        return 1.2
    elif score_total < 85:
        return 1.5
    else:
        return 1.8


# ============================================================
# Regime multiplier
# ============================================================
def _regime_multiplier(regime: str) -> float:
    """
    Multiplicateur base sur le regime de marche.

    HOT           → 1.2  (agressif)
    CHOP/UNKNOWN  → 1.0  (normal)
    COLD          → 0.7  (prudent)
    DEGRADED_EXEC → 0.6  (infra degradee)
    RUG_ENV       → 0.5  (zone dangereuse)
    """
    r = (regime or "").upper().strip()
    _map = {
        "HOT":           1.2,
        "CHOP":          1.0,
        "UNKNOWN":       1.0,
        "COLD":          0.7,
        "DEGRADED_EXEC": 0.6,
        "RUG_ENV":       0.5,
    }
    return _map.get(r, 1.0)


# ============================================================
# Risk multiplier (from risk_state)
# ============================================================
def _risk_multiplier() -> float:
    """
    Lit sizing_multiplier depuis risk_state (mis a jour par risk_engine).
    Deja calcule dans register_trade_result():
      - Reduit de 0.15 par perte consecutive (min 0.3)
      - Remonte apres 3+ wins consecutifs (max 1.0)

    Fail-open: retourne 1.0 si DB indisponible.
    """
    try:
        from core.brain_db import get_risk_state, ensure_schema
        ensure_schema()
        state = get_risk_state()
        return float(state.get("sizing_multiplier", 1.0) or 1.0)
    except Exception:
        return 1.0


# ============================================================
# Exposure check
# ============================================================
def _current_exposure_sol() -> float:
    """
    Calcule l'exposition totale actuelle (somme des positions ouvertes en SOL).
    Source: trades.sqlite → positions WHERE status LIKE 'OPEN%'.

    Fail-open: retourne 0.0 si DB indisponible.
    """
    try:
        import sqlite3
        db_path = os.getenv("TRADES_DB_PATH", os.getenv("DB_PATH", "state/trades.sqlite"))
        con = sqlite3.connect(db_path, timeout=5)
        row = con.execute(
            "SELECT COALESCE(SUM(qty_sol), 0) FROM positions WHERE status LIKE 'OPEN%'"
        ).fetchone()
        con.close()
        return float(row[0]) if row else 0.0
    except Exception:
        return 0.0


# ============================================================
# compute_sizing (public)
# ============================================================
def compute_sizing(
    score_total: float = 0.0,
    regime: str = "UNKNOWN",
    base_sol: float = 0.0,
) -> Dict[str, Any]:
    """
    Calcule la taille de position recommandee.

    Args:
        score_total: score elite 0-100
        regime: regime courant (HOT/COLD/CHOP/RUG_ENV/DEGRADED_EXEC)
        base_sol: montant de base en SOL (depuis BUY_AMOUNT_SOL env)

    Retourne:
        {
            "recommended_sol": float,    # montant final en SOL
            "recommended_lamports": int, # montant final en lamports
            "base_sol": float,
            "score_mult": float,
            "regime_mult": float,
            "risk_mult": float,
            "final_mult": float,
            "clamped": bool,             # True si le montant a ete borne
            "reason": str
        }

    Fail-open: si erreur → retourne base_sol inchange.
    """
    try:
        # Base amount
        if base_sol <= 0:
            base_sol = _fenv("BUY_AMOUNT_SOL", 0.01)

        # Bornes
        min_sol = _fenv("MIN_BUY_SOL", 0.005)
        max_sol = _fenv("MAX_BUY_SOL", 0.1)
        max_exposure = _fenv("MAX_TOTAL_EXPOSURE_SOL", 0.5)

        # Multiplicateurs
        s_mult = _score_multiplier(score_total)
        r_mult = _regime_multiplier(regime)
        risk_mult = _risk_multiplier()

        # Multiplicateur final
        final_mult = round(s_mult * r_mult * risk_mult, 4)

        # Montant recommande
        recommended = round(base_sol * final_mult, 6)

        # Clamp
        clamped = False
        reason_parts = []

        if recommended < min_sol:
            recommended = min_sol
            clamped = True
            reason_parts.append(f"clamped_min({min_sol})")

        if recommended > max_sol:
            recommended = max_sol
            clamped = True
            reason_parts.append(f"clamped_max({max_sol})")

        # Exposure check
        current_exp = _current_exposure_sol()
        remaining = max_exposure - current_exp
        if remaining <= 0:
            recommended = min_sol  # minimum vital seulement
            clamped = True
            reason_parts.append(f"max_exposure({current_exp:.3f}/{max_exposure})")
        elif recommended > remaining:
            recommended = max(min_sol, round(remaining, 6))
            clamped = True
            reason_parts.append(f"exposure_limited({remaining:.3f})")

        reason = ", ".join(reason_parts) if reason_parts else "normal"
        recommended_lamports = int(recommended * 1_000_000_000)

        result = {
            "recommended_sol":      round(recommended, 6),
            "recommended_lamports": recommended_lamports,
            "base_sol":             round(base_sol, 6),
            "score_mult":           s_mult,
            "regime_mult":          r_mult,
            "risk_mult":            round(risk_mult, 4),
            "final_mult":           final_mult,
            "clamped":              clamped,
            "reason":               reason,
        }

        # Log compact
        print(
            f"💰 SIZING: {recommended:.4f} SOL "
            f"(base={base_sol:.4f} ×score={s_mult} ×regime={r_mult} ×risk={risk_mult:.2f} "
            f"= ×{final_mult}) {reason}",
            flush=True,
        )

        return result

    except Exception as e:
        try:
            print(f"⚠️ sizing_advisor.compute_sizing failed (fail-open): {e}", flush=True)
        except Exception:
            pass
        # Fail-open: retourner le montant de base
        if base_sol <= 0:
            base_sol = _fenv("BUY_AMOUNT_SOL", 0.01)
        return {
            "recommended_sol":      round(base_sol, 6),
            "recommended_lamports": int(base_sol * 1_000_000_000),
            "base_sol":             round(base_sol, 6),
            "score_mult":           1.0,
            "regime_mult":          1.0,
            "risk_mult":            1.0,
            "final_mult":           1.0,
            "clamped":              False,
            "reason":               f"fallback:{e}",
        }
