"""
PHASE4_P4.5: Scoring Elite — score explicable multi-composantes (0-100).

Remplace progressivement le scoring simple par un score riche et explicable,
oriente vers la detection precoce des setups asymetriques.

6 composantes:
  1. score_market     (0..W_MARKET)   — qualite marche + regime
  2. score_flow       (0..W_FLOW)     — volume + momentum court terme
  3. score_history    (0..W_HISTORY)  — historique du mint (mint_memory)
  4. score_dev        (0..W_DEV)      — reputation du createur (dev_memory)
  5. score_risk       (0..W_RISK)     — risque estime (risk_state, concentration)
  6. score_execution  (0..W_EXEC)     — qualite execution (429, route fails)

Sortie:
  {
    "score_total": 0-100,
    "components": {"market": X, "flow": X, "history": X, "dev": X, "risk": X, "execution": X},
    "explain": "raison principale",
    "gate_pass": True/False
  }

Usage:
    from core.scoring_elite import score_candidate_elite
    result = score_candidate_elite(candidate_dict, mint)

Fail-open: si erreur → score_total=0, gate_pass=True (pas de blocage).
"""
from __future__ import annotations
import os
import time
from typing import Any, Dict, Optional


# ============================================================
# Configuration (env-overridable)
# ============================================================
def _fenv(name: str, default: float) -> float:
    try:
        v = os.getenv(name, "")
        return float(v) if v.strip() else float(default)
    except Exception:
        return float(default)


def _ienv(name: str, default: int) -> int:
    try:
        v = os.getenv(name, "")
        return int(float(v)) if v.strip() else int(default)
    except Exception:
        return int(default)


def _f(x, d=0.0) -> float:
    """Safe float extraction from candidate dict values."""
    try:
        if x is None:
            return float(d)
        if isinstance(x, (int, float)):
            return float(x)
        xs = str(x).strip().replace("%", "")
        if xs == "":
            return float(d)
        return float(xs)
    except Exception:
        return float(d)


# ============================================================
# Composante 1: score_market (qualite marche + regime)
# ============================================================
def _score_market(c: dict, regime: str, max_pts: float) -> float:
    """
    Evalue la qualite du marche pour ce candidat.
    - Liquidite suffisante → bonus
    - Marketcap raisonnable (pas trop gros) → bonus
    - Regime HOT → bonus, COLD → malus
    """
    liq = _f(c.get("liquidity_usd") or c.get("liq_usd") or
             (c.get("liquidity") or {}).get("usd"), 0.0)
    mc = _f(c.get("marketcap_usd") or c.get("mc_usd") or
            c.get("fdv_usd") or c.get("fdv"), 0.0)

    score = 0.0

    # Liquidite: 15k=0.3, 50k=0.6, 100k=0.8, 500k+=1.0
    if liq > 0:
        score += min(liq / 100_000.0, 1.0) * 0.4 * max_pts

    # Marketcap sweet spot: 50k-2M est ideal pour asymetrique
    if mc > 0:
        if mc < 50_000:
            score += 0.1 * max_pts   # trop petit = risque
        elif mc < 500_000:
            score += 0.3 * max_pts   # sweet spot x100
        elif mc < 2_000_000:
            score += 0.2 * max_pts   # bon potentiel x10-50
        elif mc < 10_000_000:
            score += 0.1 * max_pts   # potentiel x2-10
        # > 10M: 0 bonus (trop gros pour x100)
    else:
        score += 0.15 * max_pts  # mc inconnu → neutre

    # Regime bonus/malus
    regime_upper = regime.upper() if regime else ""
    if regime_upper == "HOT":
        score += 0.15 * max_pts
    elif regime_upper == "COLD":
        score -= 0.1 * max_pts
    elif regime_upper in ("RUG_ENV", "DEGRADED_EXEC"):
        score -= 0.15 * max_pts

    return max(0.0, min(max_pts, round(score, 2)))


# ============================================================
# Composante 2: score_flow (volume + momentum)
# ============================================================
def _score_flow(c: dict, max_pts: float) -> float:
    """
    Evalue le flux et le momentum du candidat.
    Oriente detection precoce: privilege vol5m et chg5m.
    """
    v5 = _f(c.get("vol5m_usd") or c.get("volume5m_usd") or
            c.get("vol_5m_usd") or c.get("volume_usd_5m"), 0.0)
    v1h = _f(c.get("vol1h_usd") or c.get("volume1h_usd") or
             c.get("vol_1h_usd") or c.get("volume_usd_1h"), 0.0)
    ch5 = _f(c.get("chg5m_pct") or c.get("change5m_pct") or
             c.get("priceChange5m") or (c.get("priceChange") or {}).get("m5"), 0.0)
    ch1 = _f(c.get("chg1h_pct") or c.get("change1h_pct") or
             c.get("priceChange1h") or (c.get("priceChange") or {}).get("h1"), 0.0)

    score = 0.0

    # Volume 5min: signal de debut de move
    # 3k=ok, 10k=bon, 50k+=excellent
    if v5 > 0:
        score += min(v5 / 30_000.0, 1.0) * 0.35 * max_pts

    # Volume 1h: confirme le volume
    if v1h > 0:
        score += min(v1h / 200_000.0, 1.0) * 0.15 * max_pts

    # Momentum 5min: +5% a +40% est le sweet spot
    if 5.0 <= ch5 <= 40.0:
        # Sweet spot pour catch early
        score += 0.3 * max_pts * min(ch5 / 20.0, 1.0)
    elif ch5 > 40.0:
        # Trop tard? Score reduit mais pas zero
        score += 0.15 * max_pts
    elif ch5 > 0:
        # Petit momentum positif
        score += 0.05 * max_pts

    # Momentum 1h positif = confirmation
    if ch1 > 0:
        score += min(ch1 / 30.0, 1.0) * 0.15 * max_pts

    return max(0.0, min(max_pts, round(score, 2)))


# ============================================================
# Composante 3: score_history (historique du mint)
# ============================================================
def _score_history(mint: str, max_pts: float) -> float:
    """
    Evalue l'historique du mint dans brain.sqlite → mint_memory.
    - Premier trade (inconnu) → score neutre (pas de penalite)
    - Historique positif → bonus
    - Historique negatif → malus
    """
    try:
        from core.brain_db import get_mint_memory
        mem = get_mint_memory(mint)
    except Exception:
        return round(max_pts * 0.5, 2)  # DB indisponible → neutre

    if mem is None:
        # Mint inconnu = potentiel setup nouveau (neutre-positif pour asymetrique)
        return round(max_pts * 0.6, 2)

    score = 0.0
    n_trades = int(mem.get("n_trades", 0) or 0)
    n_closed = int(mem.get("n_closed", 0) or 0)
    win_rate = float(mem.get("win_rate", 0.0) or 0.0)
    avg_pnl = float(mem.get("avg_pnl", 0.0) or 0.0)
    rug_blocks = int(mem.get("rug_block_count", 0) or 0)
    route_fails = int(mem.get("route_fail_count", 0) or 0)

    if n_closed == 0:
        # Jamais close → neutre-positif (premiere tentative)
        return round(max_pts * 0.55, 2)

    # Win rate: > 50% = bon, < 30% = mauvais
    if win_rate >= 0.6:
        score += 0.4 * max_pts
    elif win_rate >= 0.4:
        score += 0.25 * max_pts
    elif win_rate >= 0.2:
        score += 0.1 * max_pts
    # < 20% → 0

    # Avg PnL
    if avg_pnl > 0.1:
        score += 0.3 * max_pts
    elif avg_pnl > 0.0:
        score += 0.15 * max_pts
    elif avg_pnl > -0.05:
        score += 0.05 * max_pts
    # < -5% → 0

    # Penalites
    if rug_blocks > 0:
        score -= 0.2 * max_pts
    if route_fails > 2:
        score -= 0.1 * max_pts

    return max(0.0, min(max_pts, round(score, 2)))


# ============================================================
# Composante 4: score_dev (reputation createur)
# ============================================================
def _score_dev(c: dict, mint: str, max_pts: float) -> float:
    """
    Evalue la reputation du createur/deployer du token.
    Source: brain.sqlite → dev_memory.
    """
    dev_address = str(c.get("dev_address") or c.get("deployer") or
                      c.get("creator") or "").strip()

    if not dev_address:
        # Pas d'info dev → neutre
        return round(max_pts * 0.5, 2)

    try:
        from core.brain_db import get_dev_memory
        dev = get_dev_memory(dev_address)
    except Exception:
        return round(max_pts * 0.5, 2)

    if dev is None:
        # Dev inconnu = neutre (premier token vu)
        return round(max_pts * 0.5, 2)

    score = 0.0
    blacklisted = bool(dev.get("blacklisted", 0))
    n_rugged = int(dev.get("n_rugged", 0) or 0)
    n_traded = int(dev.get("n_traded", 0) or 0)
    n_profitable = int(dev.get("n_profitable", 0) or 0)
    avg_pnl = float(dev.get("avg_pnl", 0.0) or 0.0)

    # Blacklisted = score zero
    if blacklisted:
        return 0.0

    # Rugged tokens = forte penalite
    if n_rugged > 0:
        score -= min(n_rugged * 0.2, 0.6) * max_pts

    # Historique profitable
    if n_traded > 0:
        dev_wr = n_profitable / n_traded
        if dev_wr >= 0.5:
            score += 0.4 * max_pts
        elif dev_wr >= 0.3:
            score += 0.2 * max_pts
    else:
        score += 0.3 * max_pts  # pas de historique → neutre-positif

    # PnL moyen du dev
    if avg_pnl > 0.05:
        score += 0.3 * max_pts
    elif avg_pnl > 0:
        score += 0.15 * max_pts

    return max(0.0, min(max_pts, round(score, 2)))


# ============================================================
# Composante 5: score_risk (risque estime)
# ============================================================
def _score_risk(c: dict, max_pts: float) -> float:
    """
    Evalue le risque du trade.
    - risk_state: consecutive losses, drawdown jour
    - Candidat: taille, antirug flags
    Score haut = faible risque = bon pour trader.
    """
    score = max_pts  # commence au max, on retire les risques

    try:
        from core.brain_db import get_risk_state, ensure_schema
        ensure_schema()
        state = get_risk_state()

        consec_l = int(state.get("consecutive_losses", 0) or 0)
        day_dd = float(state.get("day_drawdown", 0.0) or 0.0)
        sizing_mult = float(state.get("sizing_multiplier", 1.0) or 1.0)

        # Penalite consecutive losses
        if consec_l >= 4:
            score -= 0.4 * max_pts
        elif consec_l >= 2:
            score -= 0.2 * max_pts
        elif consec_l >= 1:
            score -= 0.1 * max_pts

        # Penalite drawdown jour
        if day_dd < -0.15:
            score -= 0.3 * max_pts
        elif day_dd < -0.08:
            score -= 0.15 * max_pts

        # Sizing mult < 1 = bot deja en mode prudent
        if sizing_mult < 0.5:
            score -= 0.15 * max_pts
        elif sizing_mult < 0.8:
            score -= 0.05 * max_pts

    except Exception:
        # DB indisponible → score neutre (pas de penalite)
        score = max_pts * 0.6

    return max(0.0, min(max_pts, round(score, 2)))


# ============================================================
# Composante 6: score_execution (qualite execution)
# ============================================================
def _score_execution(max_pts: float) -> float:
    """
    Evalue la qualite d'execution recente (429, route fails, etc.).
    Source: decision_log des 15 dernieres minutes.
    """
    try:
        from core.brain_db import connect, ensure_schema
        ensure_schema()

        now = int(time.time())
        window = _ienv("SCORE_EXEC_WINDOW_SEC", 900)  # 15 min
        cutoff = now - window

        con = connect()
        rows = con.execute(
            "SELECT reason FROM decision_log WHERE ts >= ? AND action='REJECT'",
            (cutoff,),
        ).fetchall()
        total = con.execute(
            "SELECT COUNT(*) FROM decision_log WHERE ts >= ?",
            (cutoff,),
        ).fetchone()[0]
        con.close()

        if total < 3:
            # Pas assez de donnees → neutre
            return round(max_pts * 0.7, 2)

        n_429 = 0
        n_route = 0
        n_send = 0
        for row in rows:
            reason = str(row[0] or "").lower()
            if "429" in reason:
                n_429 += 1
            if "route" in reason or "swap_no_tx" in reason or "quote_http_4" in reason:
                n_route += 1
            if "send_exception" in reason or "swap_exception" in reason:
                n_send += 1

        rate_429 = n_429 / total
        rate_fail = (n_route + n_send) / total

        score = max_pts

        # Penalite 429
        if rate_429 > 0.2:
            score -= 0.4 * max_pts
        elif rate_429 > 0.1:
            score -= 0.2 * max_pts

        # Penalite route/send fails
        if rate_fail > 0.3:
            score -= 0.3 * max_pts
        elif rate_fail > 0.15:
            score -= 0.15 * max_pts

        return max(0.0, min(max_pts, round(score, 2)))

    except Exception:
        return round(max_pts * 0.6, 2)


# ============================================================
# score_candidate_elite (public)
# ============================================================
def score_candidate_elite(
    candidate: dict,
    mint: str,
    regime: str = "UNKNOWN",
) -> Dict[str, Any]:
    """
    Score un candidat avec le scoring elite multi-composantes.

    Args:
        candidate: dict du candidat (depuis ready_to_trade.jsonl)
        mint: adresse du token
        regime: regime courant (depuis regime_detector)

    Retourne:
        {
            "score_total": 0-100,
            "components": {"market": X, "flow": X, "history": X, "dev": X, "risk": X, "execution": X},
            "explain": "raison principale",
            "gate_pass": True/False
        }

    Fail-open: si erreur globale → score_total=0, gate_pass=True.
    """
    try:
        # Poids (env-configurable)
        w_market = _fenv("SCORE_W_MARKET", 20.0)
        w_flow   = _fenv("SCORE_W_FLOW", 20.0)
        w_hist   = _fenv("SCORE_W_HISTORY", 15.0)
        w_dev    = _fenv("SCORE_W_DEV", 15.0)
        w_risk   = _fenv("SCORE_W_RISK", 15.0)
        w_exec   = _fenv("SCORE_W_EXECUTION", 15.0)

        # Score minimum pour autoriser BUY (0 = desactive)
        min_buy  = _fenv("SCORE_MIN_BUY", 0.0)

        # Calculer chaque composante
        s_market = _score_market(candidate, regime, w_market)
        s_flow   = _score_flow(candidate, w_flow)
        s_hist   = _score_history(mint, w_hist)
        s_dev    = _score_dev(candidate, mint, w_dev)
        s_risk   = _score_risk(candidate, w_risk)
        s_exec   = _score_execution(w_exec)

        total = round(s_market + s_flow + s_hist + s_dev + s_risk + s_exec, 2)
        total = max(0.0, min(100.0, total))

        # Gate pass
        gate_pass = True
        if min_buy > 0 and total < min_buy:
            gate_pass = False

        # Explain: composante dominante + resume
        components = {
            "market": s_market,
            "flow": s_flow,
            "history": s_hist,
            "dev": s_dev,
            "risk": s_risk,
            "execution": s_exec,
        }
        # Trouver la composante la plus forte et la plus faible
        sorted_comp = sorted(components.items(), key=lambda x: x[1], reverse=True)
        best_name, best_val = sorted_comp[0]
        worst_name, worst_val = sorted_comp[-1]

        explain = (
            f"score={total:.0f}/100 best={best_name}({best_val:.1f}) "
            f"worst={worst_name}({worst_val:.1f}) regime={regime}"
        )

        result = {
            "score_total": total,
            "components": components,
            "explain": explain,
            "gate_pass": gate_pass,
        }

        # Log compact
        print(
            f"📊 SCORE_ELITE: {total:.0f}/100 "
            f"[M={s_market:.0f} F={s_flow:.0f} H={s_hist:.0f} D={s_dev:.0f} R={s_risk:.0f} E={s_exec:.0f}] "
            f"regime={regime} gate={'PASS' if gate_pass else 'BLOCK'}",
            flush=True,
        )

        return result

    except Exception as e:
        try:
            print(f"⚠️ scoring_elite failed (fail-open): {e}", flush=True)
        except Exception:
            pass
        return {
            "score_total": 0.0,
            "components": {
                "market": 0.0, "flow": 0.0, "history": 0.0,
                "dev": 0.0, "risk": 0.0, "execution": 0.0,
            },
            "explain": f"scoring_error:{e}",
            "gate_pass": True,  # fail-open: ne jamais bloquer sur erreur
        }
