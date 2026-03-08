"""
PHASE4_P4.4: Regime Detector — detection automatique du regime de marche.

Analyse les decisions recentes (decision_log) + l'etat risk (risk_state)
pour determiner le regime courant du marche.

Regimes detectes (par priorite):
  1. DEGRADED_EXEC — infrastructure degradee (429, send fails)
  2. RUG_ENV       — environnement a haut risque de rug (antirug blocks, route fails)
  3. HOT           — marche favorable (win rate eleve, pnl positif)
  4. COLD          — marche defavorable (win rate bas, pnl negatif)
  5. CHOP          — marche sans direction claire

Chaque detection produit:
  - regime: str           — nom du regime
  - regime_score: float   — -1.0 (tres mauvais) a +1.0 (tres bon)
  - confidence: float     — 0.0 (pas assez de donnees) a 1.0 (haute confiance)
  - reason: str           — explication principale
  - metrics: dict         — toutes les metriques calculees

Usage:
    from core.regime_detector import detect_regime, get_current_regime
    regime = detect_regime()        # calcule + stocke snapshot
    regime = get_current_regime()   # lit le dernier snapshot (pas de recalcul)

Fail-open: si erreur → regime="UNKNOWN", confidence=0.
Lecture seule sur decision_log + risk_state. Ecriture uniquement dans regime_snapshots.
Branchement futur prevu vers: scoring_elite, sizing_advisor, trailing adaptatif, risk_engine.
"""
from __future__ import annotations
import json
import os
import time
from typing import Any, Dict, Optional, Tuple


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


# ============================================================
# Metrics collector
# ============================================================
def _collect_metrics(window_sec: int = 0) -> Dict[str, Any]:
    """
    Collecte les metriques depuis decision_log (fenetre) + risk_state (jour).
    Retourne un dict avec toutes les metriques brutes.
    Fail-open: retourne un dict vide si erreur.
    """
    if window_sec <= 0:
        window_sec = _ienv("REGIME_WINDOW_SEC", 1800)

    try:
        from core.brain_db import connect, ensure_schema, get_risk_state
        ensure_schema()

        now = int(time.time())
        cutoff = now - window_sec

        con = connect()

        # --- Compteurs depuis decision_log (fenetre glissante) ---
        rows = con.execute(
            "SELECT action, reason FROM decision_log WHERE ts >= ?",
            (cutoff,),
        ).fetchall()
        con.close()

        n_total = len(rows)
        n_buy = 0
        n_reject = 0
        n_skip = 0
        n_429 = 0
        n_route_fail = 0
        n_antirug = 0
        n_send_fail = 0
        n_quote_fail = 0

        for row in rows:
            action = str(row[0] or "").upper()
            reason = str(row[1] or "").lower()

            if action == "BUY":
                n_buy += 1
            elif action == "REJECT":
                n_reject += 1
            elif action == "SKIP":
                n_skip += 1

            # Classification des raisons
            if "quote_http_429" in reason:
                n_429 += 1
            elif reason.startswith("quote_http_") or reason == "quote_exception":
                n_quote_fail += 1
            if reason == "swap_no_tx" or reason.startswith("swap_http_"):
                n_route_fail += 1
            if reason.startswith("antirug"):
                n_antirug += 1
            if reason in ("send_exception", "swap_exception"):
                n_send_fail += 1

        # Taux (safe division)
        def _rate(n: int, total: int) -> float:
            return round(n / total, 4) if total > 0 else 0.0

        rate_429 = _rate(n_429, n_total)
        rate_route_fail = _rate(n_route_fail + n_quote_fail, n_total)
        rate_antirug = _rate(n_antirug, n_total)
        rate_send_fail = _rate(n_send_fail, n_total)
        rate_reject = _rate(n_reject, n_total)
        rate_skip = _rate(n_skip, n_total)

        # --- Stats jour depuis risk_state ---
        state = get_risk_state()
        day_trades = int(state.get("day_trades", 0) or 0)
        day_wins = int(state.get("day_wins", 0) or 0)
        day_losses = int(state.get("day_losses", 0) or 0)
        day_pnl = float(state.get("day_pnl", 0.0) or 0.0)
        consec_losses = int(state.get("consecutive_losses", 0) or 0)

        win_rate = round(day_wins / day_trades, 4) if day_trades > 0 else 0.0
        avg_pnl = round(day_pnl / day_trades, 6) if day_trades > 0 else 0.0

        return {
            # Fenetre decision_log
            "window_sec":       window_sec,
            "n_decisions":      n_total,
            "n_buy":            n_buy,
            "n_reject":         n_reject,
            "n_skip":           n_skip,
            "n_429":            n_429,
            "n_route_fail":     n_route_fail + n_quote_fail,
            "n_antirug":        n_antirug,
            "n_send_fail":      n_send_fail,
            "rate_429":         rate_429,
            "rate_route_fail":  rate_route_fail,
            "rate_antirug":     rate_antirug,
            "rate_send_fail":   rate_send_fail,
            "rate_reject":      rate_reject,
            "rate_skip":        rate_skip,
            # Stats jour (risk_state)
            "day_trades":       day_trades,
            "day_wins":         day_wins,
            "day_losses":       day_losses,
            "day_pnl":          day_pnl,
            "win_rate":         win_rate,
            "avg_pnl":          avg_pnl,
            "consec_losses":    consec_losses,
        }

    except Exception as e:
        try:
            print(f"⚠️ regime_detector._collect_metrics failed (non-fatal): {e}", flush=True)
        except Exception:
            pass
        return {}


# ============================================================
# Regime classification
# ============================================================
def _classify(metrics: Dict[str, Any]) -> Tuple[str, float, float, str]:
    """
    Classe le regime a partir des metriques.

    Retourne (regime, score, confidence, reason).

    Priorite de detection:
      1. DEGRADED_EXEC (infrastructure)
      2. RUG_ENV (securite)
      3. HOT / COLD / CHOP (performance)
    """
    if not metrics:
        return "UNKNOWN", 0.0, 0.0, "no_metrics"

    # --- Seuils (lus a chaque appel) ---
    min_decisions    = _ienv("REGIME_MIN_DECISIONS", 5)
    min_trades       = _ienv("REGIME_MIN_TRADES", 3)

    thresh_429       = _fenv("REGIME_429_THRESHOLD", 0.20)
    thresh_send_fail = _fenv("REGIME_SEND_FAIL_THRESHOLD", 0.15)
    thresh_antirug   = _fenv("REGIME_ANTIRUG_THRESHOLD", 0.20)
    thresh_route     = _fenv("REGIME_ROUTE_FAIL_THRESHOLD", 0.40)
    thresh_hot_wr    = _fenv("REGIME_HOT_WIN_RATE", 0.50)
    thresh_hot_pnl   = _fenv("REGIME_HOT_AVG_PNL", 0.03)
    thresh_cold_wr   = _fenv("REGIME_COLD_WIN_RATE", 0.25)
    thresh_cold_pnl  = _fenv("REGIME_COLD_AVG_PNL", -0.08)

    # --- Metriques ---
    n_decisions  = int(metrics.get("n_decisions", 0))
    rate_429     = float(metrics.get("rate_429", 0.0))
    rate_send    = float(metrics.get("rate_send_fail", 0.0))
    rate_antirug = float(metrics.get("rate_antirug", 0.0))
    rate_route   = float(metrics.get("rate_route_fail", 0.0))
    win_rate     = float(metrics.get("win_rate", 0.0))
    avg_pnl      = float(metrics.get("avg_pnl", 0.0))
    day_trades   = int(metrics.get("day_trades", 0))
    consec_l     = int(metrics.get("consec_losses", 0))

    # --- Confiance basee sur le volume de donnees ---
    if n_decisions < min_decisions and day_trades < min_trades:
        return "UNKNOWN", 0.0, 0.1, f"insufficient_data: {n_decisions} decisions, {day_trades} trades"

    confidence = min(1.0, n_decisions / max(min_decisions * 3, 1))

    # --- 1. DEGRADED_EXEC (priorite max: infra cassee) ---
    if rate_429 >= thresh_429:
        score = -0.8 - min(0.2, rate_429)
        return "DEGRADED_EXEC", round(score, 3), round(confidence, 3), \
            f"rate_429={rate_429:.1%} >= {thresh_429:.0%}"

    if rate_send >= thresh_send_fail:
        score = -0.7 - min(0.3, rate_send)
        return "DEGRADED_EXEC", round(score, 3), round(confidence, 3), \
            f"rate_send_fail={rate_send:.1%} >= {thresh_send_fail:.0%}"

    # --- 2. RUG_ENV (securite degradee) ---
    if rate_antirug >= thresh_antirug:
        score = -0.6 - min(0.3, rate_antirug)
        return "RUG_ENV", round(score, 3), round(confidence, 3), \
            f"rate_antirug={rate_antirug:.1%} >= {thresh_antirug:.0%}"

    if rate_route >= thresh_route:
        score = -0.5 - min(0.3, rate_route)
        return "RUG_ENV", round(score, 3), round(confidence, 3), \
            f"rate_route_fail={rate_route:.1%} >= {thresh_route:.0%}"

    # --- 3. HOT / COLD / CHOP (performance) ---
    # Besoin d'au moins min_trades closes pour juger
    if day_trades >= min_trades:
        if win_rate >= thresh_hot_wr and avg_pnl >= thresh_hot_pnl:
            # HOT: marche favorable
            score = 0.5 + min(0.5, win_rate * 0.5 + avg_pnl * 2)
            return "HOT", round(min(1.0, score), 3), round(confidence, 3), \
                f"win_rate={win_rate:.0%} avg_pnl={avg_pnl:+.2%}"

        if win_rate <= thresh_cold_wr or avg_pnl <= thresh_cold_pnl:
            # COLD: marche defavorable
            score = -0.3 + max(-0.5, avg_pnl * 3)
            return "COLD", round(max(-1.0, score), 3), round(confidence, 3), \
                f"win_rate={win_rate:.0%} avg_pnl={avg_pnl:+.2%} consec_l={consec_l}"

    # --- 4. CHOP: pas de direction claire ---
    score = 0.0
    return "CHOP", round(score, 3), round(confidence, 3), \
        f"win_rate={win_rate:.0%} avg_pnl={avg_pnl:+.2%} (no clear signal)"


# ============================================================
# detect_regime (public)
# ============================================================
def detect_regime(window_sec: int = 0) -> Dict[str, Any]:
    """
    Calcule le regime courant et stocke un snapshot dans brain.sqlite.

    Retourne un dict avec:
      - regime: str
      - regime_score: float (-1 a +1)
      - confidence: float (0 a 1)
      - reason: str
      - metrics: dict (toutes les metriques brutes)
      - ts: int

    Fail-open: retourne regime=UNKNOWN si erreur.
    """
    try:
        metrics = _collect_metrics(window_sec)
        regime, score, confidence, reason = _classify(metrics)

        result = {
            "regime":       regime,
            "regime_score": score,
            "confidence":   confidence,
            "reason":       reason,
            "metrics":      metrics,
            "ts":           int(time.time()),
        }

        # Stocker le snapshot
        try:
            from core.brain_db import insert_regime_snapshot
            snapshot_data = {
                "ts":            result["ts"],
                "window_sec":    int(metrics.get("window_sec", 1800)),
                "n_trades":      int(metrics.get("day_trades", 0)),
                "n_wins":        int(metrics.get("day_wins", 0)),
                "n_losses":      int(metrics.get("day_losses", 0)),
                "win_rate":      float(metrics.get("win_rate", 0.0)),
                "avg_pnl":       float(metrics.get("avg_pnl", 0.0)),
                "n_buys":        int(metrics.get("n_buy", 0)),
                "n_sells":       0,  # sera enrichi quand sell_engine trace aussi
                "n_429":         int(metrics.get("n_429", 0)),
                "n_route_fail":  int(metrics.get("n_route_fail", 0)),
                "n_rug_block":   int(metrics.get("n_antirug", 0)),
                "regime":        regime,
                "regime_score":  score,
                "confidence":    confidence,
                "details_json":  json.dumps({
                    "reason": reason,
                    "rate_429":        float(metrics.get("rate_429", 0.0)),
                    "rate_route_fail": float(metrics.get("rate_route_fail", 0.0)),
                    "rate_antirug":    float(metrics.get("rate_antirug", 0.0)),
                    "rate_send_fail":  float(metrics.get("rate_send_fail", 0.0)),
                    "consec_losses":   int(metrics.get("consec_losses", 0)),
                }, ensure_ascii=False),
            }
            insert_regime_snapshot(snapshot_data)
        except Exception as e:
            try:
                print(f"⚠️ regime_detector snapshot write failed (non-fatal): {e}", flush=True)
            except Exception:
                pass

        # Log lisible
        _icons = {
            "HOT": "🔥", "COLD": "🧊", "CHOP": "🔀",
            "RUG_ENV": "☠️", "DEGRADED_EXEC": "⚡", "UNKNOWN": "❓",
        }
        icon = _icons.get(regime, "❓")
        print(
            f"{icon} REGIME={regime} score={score:+.3f} conf={confidence:.2f} | {reason}",
            flush=True,
        )

        return result

    except Exception as e:
        try:
            print(f"⚠️ regime_detector.detect_regime failed (fail-open): {e}", flush=True)
        except Exception:
            pass
        return {
            "regime": "UNKNOWN", "regime_score": 0.0,
            "confidence": 0.0, "reason": f"error:{e}",
            "metrics": {}, "ts": int(time.time()),
        }


# ============================================================
# get_current_regime (public, pas de recalcul)
# ============================================================
def get_current_regime() -> Dict[str, Any]:
    """
    Lit le dernier regime snapshot sans recalcul.
    Rapide (1 requete SELECT).
    Fail-open: retourne regime=UNKNOWN si pas de snapshot.
    """
    try:
        from core.brain_db import get_latest_regime
        snap = get_latest_regime()
        if snap is None:
            return {"regime": "UNKNOWN", "regime_score": 0.0, "confidence": 0.0, "reason": "no_snapshot"}

        return {
            "regime":       snap.get("regime", "UNKNOWN"),
            "regime_score": float(snap.get("regime_score", 0.0) or 0.0),
            "confidence":   float(snap.get("confidence", 0.0) or 0.0),
            "reason":       "",
            "ts":           int(snap.get("ts", 0) or 0),
        }
    except Exception as e:
        try:
            print(f"⚠️ regime_detector.get_current_regime failed (fail-open): {e}", flush=True)
        except Exception:
            pass
        return {"regime": "UNKNOWN", "regime_score": 0.0, "confidence": 0.0, "reason": f"error:{e}"}


# ============================================================
# CLI standalone
# ============================================================
if __name__ == "__main__":
    print("[REGIME_DETECTOR] Running detection...")
    result = detect_regime()
    print(f"[REGIME_DETECTOR] Result: {json.dumps(result, indent=2, default=str)}")
