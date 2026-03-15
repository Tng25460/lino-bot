"""
PHASE4_P4.3: Risk Engine Elite.

Gestion du risque en temps reel avec circuit breaker automatique.

Fonctions publiques:
  - check_circuit_breaker() -> (allowed, reason)
  - register_trade_result(pnl, close_reason, mint, sizing_sol)
  - get_risk_summary() -> dict

Regles:
  - Circuit breaker déclenché si:
    * day_pnl < -MAX_LOSS_DAY_PCT (perte jour excessive)
    * consecutive_losses >= MAX_CONSECUTIVE_LOSSES
    * day_drawdown < -MAX_DRAWDOWN_DAY_PCT
    * day_trades >= MAX_TRADES_DAY
  - Circuit breaker actif → BUY bloqué, SELL toujours autorisé
  - Durée circuit breaker: CIRCUIT_BREAKER_COOLDOWN_SEC (defaut 600s = 10min)
  - Sizing multiplier ajusté dynamiquement selon risque

Connexion: brain_db.risk_state (singleton id=1, reset auto journalier).
Fail-open obligatoire: si brain_db indisponible, on autorise le trading.
"""
from __future__ import annotations
import os
import time
from typing import Any, Dict, Tuple


# ============================================================
# Configuration (env-overridable avec defaults safe)
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
# check_circuit_breaker
# ============================================================
def check_circuit_breaker() -> Tuple[bool, str]:

    # PATCH VNEXT: fail-open si circuit breaker global desactive
    try:
        _risk_cb_disabled = os.getenv("RISK_CB_DISABLE", "").strip().lower() in ("1", "true", "yes", "on")
        _risk_cb_disabled = _risk_cb_disabled or os.getenv("RISK_DISABLE_CIRCUIT_BREAKER", "").strip().lower() in ("1", "true", "yes", "on")
        _risk_cb_disabled = _risk_cb_disabled or os.getenv("CIRCUIT_BREAKER_ENABLED", "1").strip().lower() in ("0", "false", "no", "off")
        if _risk_cb_disabled:
            try:
                _st = _load_state()
                if isinstance(_st, dict):
                    _st["circuit_breaker_until"] = 0
                    _st["circuit_breaker_reason"] = ""
                    try:
                        _save_state(_st)
                    except Exception:
                        pass
            except Exception:
                pass
            print("🟢 RISK_ENGINE fail-open: circuit breaker disabled by env", flush=True)
            return True, "risk_cb_disabled"
    except Exception:
        pass
    """
    Vérifie si le circuit breaker est actif.

    Retourne:
      (True, "")      → trading autorisé
      (False, reason)  → BUY bloqué, reason explique pourquoi

    Fail-open: si erreur DB/brain_db → (True, "")
    Les SELL ne sont JAMAIS bloqués (cette fonction ne concerne que BUY).
    """
    try:
        from core.brain_db import get_risk_state, ensure_schema
        ensure_schema()

        state = get_risk_state()

        # --- Seuils (lus à chaque appel pour supporter hot-reload .env) ---
        max_loss_day_pct     = _fenv("RISK_MAX_LOSS_DAY_PCT", 0.15)       # 15% du capital jour
        max_consecutive      = _ienv("RISK_MAX_CONSECUTIVE_LOSSES", 5)
        max_drawdown_day_pct = _fenv("RISK_MAX_DRAWDOWN_DAY_PCT", 0.20)   # 20%
        max_trades_day       = _ienv("RISK_MAX_TRADES_DAY", 50)
        cb_cooldown_sec      = _ienv("RISK_CIRCUIT_BREAKER_SEC", 600)     # 10 min

        now = int(time.time())

        # 1) Circuit breaker temporel déjà actif ?
        cb_until = int(state.get("circuit_breaker_until", 0) or 0)
        if cb_until > now:
            remaining = cb_until - now
            reason = state.get("circuit_breaker_reason", "active")
            return False, f"circuit_breaker_active: {reason} (expires in {remaining}s)"

        # 2) Max trades jour
        day_trades = int(state.get("day_trades", 0) or 0)
        if max_trades_day > 0 and day_trades >= max_trades_day:
            _activate_breaker(state, f"max_trades_day={day_trades}/{max_trades_day}", cb_cooldown_sec)
            return False, f"max_trades_day: {day_trades}/{max_trades_day}"

        # 3) Consecutive losses
        consec = int(state.get("consecutive_losses", 0) or 0)
        if max_consecutive > 0 and consec >= max_consecutive:
            _activate_breaker(state, f"consecutive_losses={consec}/{max_consecutive}", cb_cooldown_sec)
            return False, f"consecutive_losses: {consec}/{max_consecutive}"

        # 4) Daily PnL loss
        day_pnl = float(state.get("day_pnl", 0.0) or 0.0)
        if max_loss_day_pct > 0 and day_pnl < -max_loss_day_pct:
            _activate_breaker(state, f"day_pnl={day_pnl:.4f}/max=-{max_loss_day_pct}", cb_cooldown_sec)
            return False, f"max_loss_day: pnl={day_pnl:.4f} < -{max_loss_day_pct}"

        # 5) Daily drawdown
        day_dd = float(state.get("day_drawdown", 0.0) or 0.0)
        if max_drawdown_day_pct > 0 and day_dd < -max_drawdown_day_pct:
            _activate_breaker(state, f"day_drawdown={day_dd:.4f}/max=-{max_drawdown_day_pct}", cb_cooldown_sec)
            return False, f"max_drawdown_day: dd={day_dd:.4f} < -{max_drawdown_day_pct}"

        return True, ""

    except Exception as e:
        # Fail-open: DB indisponible → on autorise
        try:
            print(f"⚠️ risk_engine.check_circuit_breaker failed (fail-open): {e}", flush=True)
        except Exception:
            pass
        return True, ""


def _activate_breaker(state: Dict[str, Any], reason: str, cooldown_sec: int) -> None:

    try:
        _risk_cb_disabled = os.getenv("RISK_CB_DISABLE", "").strip().lower() in ("1", "true", "yes", "on")
        _risk_cb_disabled = _risk_cb_disabled or os.getenv("RISK_DISABLE_CIRCUIT_BREAKER", "").strip().lower() in ("1", "true", "yes", "on")
        _risk_cb_disabled = _risk_cb_disabled or os.getenv("CIRCUIT_BREAKER_ENABLED", "1").strip().lower() in ("0", "false", "no", "off")
        if _risk_cb_disabled:
            print("🟢 RISK_ENGINE breaker activation skipped (disabled by env)", flush=True)
            return
    except Exception:
        pass
    """Active le circuit breaker pour cooldown_sec secondes."""
    try:
        from core.brain_db import update_risk_state
        until = int(time.time()) + cooldown_sec
        update_risk_state({
            "circuit_breaker_until": until,
            "circuit_breaker_reason": str(reason),
        })
        print(f"🛑 CIRCUIT_BREAKER ACTIVATED: {reason} → blocked for {cooldown_sec}s", flush=True)
    except Exception as e:
        try:
            print(f"⚠️ risk_engine._activate_breaker failed (non-fatal): {e}", flush=True)
        except Exception:
            pass


# ============================================================
# register_trade_result
# ============================================================
def register_trade_result(
    pnl_pct: float,
    close_reason: str = "",
    mint: str = "",
    sizing_sol: float = 0.0,
) -> None:
    """
    Appelé après chaque fermeture de position (close_position dans sell_engine).

    Args:
        pnl_pct:      PnL en pourcentage (ex: 0.15 = +15%, -0.08 = -8%)
        close_reason:  raison de la fermeture (hard_sl, tp1, tp2, trailing_stop, time_stop)
        mint:          adresse du token
        sizing_sol:    taille de la position en SOL

    Met à jour:
        - day_trades, day_wins, day_losses, day_pnl
        - day_max_pnl (high water mark), day_drawdown
        - consecutive_losses / consecutive_wins
        - sizing_multiplier (ajusté dynamiquement)
        - risk_budget_used

    Fail-open: si erreur → warning print, pas de crash.
    """
    try:
        from core.brain_db import get_risk_state, update_risk_state, ensure_schema
        ensure_schema()

        state = get_risk_state()
        is_win = (pnl_pct > 0)

        # --- Compteurs ---
        day_trades = int(state.get("day_trades", 0) or 0) + 1
        day_wins   = int(state.get("day_wins", 0) or 0) + (1 if is_win else 0)
        day_losses = int(state.get("day_losses", 0) or 0) + (0 if is_win else 1)
        day_pnl    = float(state.get("day_pnl", 0.0) or 0.0) + float(pnl_pct)

        # --- High water mark et drawdown ---
        day_max_pnl = float(state.get("day_max_pnl", 0.0) or 0.0)
        if day_pnl > day_max_pnl:
            day_max_pnl = day_pnl
        current_dd = day_pnl - day_max_pnl  # toujours <= 0
        day_drawdown = float(state.get("day_drawdown", 0.0) or 0.0)
        if current_dd < day_drawdown:
            day_drawdown = current_dd

        # --- Consecutive losses/wins ---
        if is_win:
            consec_losses = 0
            consec_wins = int(state.get("consecutive_wins", 0) or 0) + 1
        else:
            consec_losses = int(state.get("consecutive_losses", 0) or 0) + 1
            consec_wins = 0

        max_consec_losses = int(state.get("max_consecutive_losses", 0) or 0)
        if consec_losses > max_consec_losses:
            max_consec_losses = consec_losses

        # --- Sizing multiplier dynamique ---
        #  Base = 1.0
        #  Réduit de 0.15 par perte consécutive (min 0.3)
        #  Augmenté de 0.1 par win consécutive (max 1.0)
        sizing_mult = 1.0
        if consec_losses > 0:
            sizing_mult = max(0.3, 1.0 - (consec_losses * 0.15))
        elif consec_wins >= 3:
            sizing_mult = min(1.0, 0.8 + (consec_wins * 0.1))

        # --- Risk budget ---
        risk_budget_used = float(state.get("risk_budget_used", 0.0) or 0.0)
        if sizing_sol > 0:
            risk_budget_used += float(sizing_sol)

        # --- Écriture atomique ---
        updates = {
            "day_trades":             day_trades,
            "day_wins":               day_wins,
            "day_losses":             day_losses,
            "day_pnl":                round(day_pnl, 6),
            "day_max_pnl":            round(day_max_pnl, 6),
            "day_drawdown":           round(day_drawdown, 6),
            "consecutive_losses":     consec_losses,
            "max_consecutive_losses": max_consec_losses,
            "consecutive_wins":       consec_wins,
            "sizing_multiplier":      round(sizing_mult, 4),
            "risk_budget_used":       round(risk_budget_used, 6),
        }
        update_risk_state(updates)

        # Log résumé
        icon = "🟢" if is_win else "🔴"
        print(
            f"{icon} RISK_ENGINE: pnl={pnl_pct:+.2%} reason={close_reason} "
            f"day={day_trades}t/{day_wins}w/{day_losses}l pnl_day={day_pnl:+.4f} "
            f"dd={day_drawdown:.4f} consec_l={consec_losses} sizing={sizing_mult:.2f}",
            flush=True,
        )

        # ================================================================
        # PRIO1_E: POST-TRADE LOGGER — JSONL append
        # Stocke chaque trade fermé pour analyse et recalibration.
        # Fichier: state/post_trade_log.jsonl (configurable via POST_TRADE_LOG)
        # Fail-safe: ne crash jamais le bot.
        # ================================================================
        try:
            import json as _ptl_json
            import time as _ptl_time
            _ptl_path = os.getenv("POST_TRADE_LOG", "state/post_trade_log.jsonl")
            _ptl_now = _ptl_time.time()

            _ptl_entry = {
                "ts": int(_ptl_now),
                "mint": str(mint),
                "pnl_pct": round(float(pnl_pct), 6),
                "close_reason": str(close_reason),
                "sizing_sol": round(float(sizing_sol), 6) if sizing_sol else 0.0,
                "day_trades": day_trades,
                "day_pnl": round(day_pnl, 6),
                "day_drawdown": round(day_drawdown, 6),
                "consecutive_losses": consec_losses,
                "sizing_multiplier": round(sizing_mult, 4),
                "is_win": is_win,
            }

            # Append atomique
            os.makedirs(os.path.dirname(_ptl_path) or ".", exist_ok=True)
            with open(_ptl_path, "a", encoding="utf-8") as _ptl_f:
                _ptl_f.write(_ptl_json.dumps(_ptl_entry, ensure_ascii=False) + "\n")

            print(f"📝 POST_TRADE_LOGGED mint={mint[:16]}… pnl={pnl_pct:+.2%} reason={close_reason}", flush=True)
        except Exception as _ptl_e:
            try:
                print(f"⚠️ POST_TRADE_LOG failed (non-fatal): {_ptl_e}", flush=True)
            except Exception:
                pass
        # --- /PRIO1_E: POST-TRADE LOGGER ---

    except Exception as e:
        try:
            print(f"⚠️ risk_engine.register_trade_result failed (non-fatal): {e}", flush=True)
        except Exception:
            pass


# ============================================================
# get_risk_summary
# ============================================================
def get_risk_summary() -> Dict[str, Any]:
    """
    Retourne un résumé lisible de l'état du risk engine.
    Fail-open: retourne dict vide si erreur.
    """
    try:
        from core.brain_db import get_risk_state, ensure_schema
        ensure_schema()

        state = get_risk_state()
        now = int(time.time())
        cb_until = int(state.get("circuit_breaker_until", 0) or 0)

        return {
            "day_date":           state.get("day_date", ""),
            "day_trades":         int(state.get("day_trades", 0) or 0),
            "day_wins":           int(state.get("day_wins", 0) or 0),
            "day_losses":         int(state.get("day_losses", 0) or 0),
            "day_pnl":            float(state.get("day_pnl", 0.0) or 0.0),
            "day_drawdown":       float(state.get("day_drawdown", 0.0) or 0.0),
            "consecutive_losses": int(state.get("consecutive_losses", 0) or 0),
            "consecutive_wins":   int(state.get("consecutive_wins", 0) or 0),
            "sizing_multiplier":  float(state.get("sizing_multiplier", 1.0) or 1.0),
            "circuit_breaker":    cb_until > now,
            "cb_reason":          state.get("circuit_breaker_reason", ""),
            "cb_remaining_sec":   max(0, cb_until - now),
            "risk_budget_used":   float(state.get("risk_budget_used", 0.0) or 0.0),
        }
    except Exception as e:
        try:
            print(f"⚠️ risk_engine.get_risk_summary failed (non-fatal): {e}", flush=True)
        except Exception:
            pass
        return {}
