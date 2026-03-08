"""
PHASE4_P4.2: Trace non-bloquante de chaque decision BUY/REJECT/SKIP.

Chaque appel a trace() enregistre dans brain.sqlite → decision_log.
- Non-bloquant : l'insertion se fait dans un thread separe
- Fail-open : si la DB est indisponible, on print un warning et on continue
- Zero latence ajoutee au pipeline de trading

Usage dans trader_exec.py :
    from core.decision_trace import trace
    trace("REJECT", mint, reason="liq_too_low", score_market=2.1, ...)
    trace("BUY", mint, score_total=28.5, sizing_sol=0.05, ...)
"""
from __future__ import annotations
import os
import threading
import time
from typing import Any, Dict, List, Optional

# PHASE4_P4.2_FIX: tracking des threads pour flush avant exit subprocess
_pending_threads: List[threading.Thread] = []
_pending_lock = threading.Lock()


def trace(
    action: str,
    mint: str,
    *,
    reason: str = "",
    symbol: str = "",
    score_total: float = 0.0,
    score_market: float = 0.0,
    score_flow: float = 0.0,
    score_history: float = 0.0,
    score_dev: float = 0.0,
    score_risk: float = 0.0,
    score_execution: float = 0.0,
    regime: str = "",
    sizing_sol: float = 0.0,
    profile: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Enregistre une decision de maniere non-bloquante.
    Le thread d'insertion est fire-and-forget.
    Si quoi que ce soit echoue → warning print, pas de crash.
    """
    try:
        # Construire le payload avant le thread (pas d'acces concurrent aux locals)
        payload = {
            "action": str(action),
            "mint": str(mint or ""),
            "reason": str(reason),
            "symbol": str(symbol),
            "score_total": float(score_total),
            "score_market": float(score_market),
            "score_flow": float(score_flow),
            "score_history": float(score_history),
            "score_dev": float(score_dev),
            "score_risk": float(score_risk),
            "score_execution": float(score_execution),
            "regime": str(regime),
            "sizing_sol": float(sizing_sol),
            "profile": str(profile),
            "details": details,
        }
        t = threading.Thread(target=_insert, args=(payload,), daemon=True)
        t.start()
        # PHASE4_P4.2_FIX: tracker pour flush_pending()
        with _pending_lock:
            _pending_threads[:] = [th for th in _pending_threads if th.is_alive()]
            _pending_threads.append(t)
    except Exception as e:
        # Fail-open: ne jamais bloquer le pipeline
        try:
            print(f"⚠️ decision_trace.trace failed (non-fatal): {e}", flush=True)
        except Exception:
            pass


def _insert(payload: Dict[str, Any]) -> None:
    """Insertion dans brain.sqlite (appele dans un thread separe)."""
    try:
        from core.brain_db import log_decision, ensure_schema

        # S'assurer que le schema existe (idempotent, ~0ms apres le 1er appel)
        ensure_schema()

        log_decision(
            mint=payload["mint"],
            action=payload["action"],
            reason=payload["reason"],
            symbol=payload["symbol"],
            score_total=payload["score_total"],
            score_market=payload["score_market"],
            score_flow=payload["score_flow"],
            score_history=payload["score_history"],
            score_dev=payload["score_dev"],
            score_risk=payload["score_risk"],
            score_execution=payload["score_execution"],
            regime=payload["regime"],
            sizing_sol=payload["sizing_sol"],
            profile=payload["profile"],
            details=payload["details"],
        )
    except Exception as e:
        try:
            print(f"⚠️ decision_trace._insert failed (non-fatal): {e}", flush=True)
        except Exception:
            pass


def trace_sync(
    action: str,
    mint: str,
    **kwargs,
) -> None:
    """
    Version synchrone (pour les cas ou on veut garantir l'ecriture).
    Meme signature que trace() mais bloquante.
    Fail-open quand meme.
    """
    try:
        from core.brain_db import log_decision, ensure_schema

        ensure_schema()
        log_decision(
            mint=mint,
            action=action,
            reason=kwargs.get("reason", ""),
            symbol=kwargs.get("symbol", ""),
            score_total=kwargs.get("score_total", 0.0),
            score_market=kwargs.get("score_market", 0.0),
            score_flow=kwargs.get("score_flow", 0.0),
            score_history=kwargs.get("score_history", 0.0),
            score_dev=kwargs.get("score_dev", 0.0),
            score_risk=kwargs.get("score_risk", 0.0),
            score_execution=kwargs.get("score_execution", 0.0),
            regime=kwargs.get("regime", ""),
            sizing_sol=kwargs.get("sizing_sol", 0.0),
            profile=kwargs.get("profile", ""),
            details=kwargs.get("details"),
        )
    except Exception as e:
        try:
            print(f"⚠️ decision_trace.trace_sync failed (non-fatal): {e}", flush=True)
        except Exception:
            pass


def flush_pending(timeout: float = 2.0) -> int:
    """
    PHASE4_P4.2_FIX: Attend la fin des threads de trace en attente.

    Doit etre appele avant la sortie d'un subprocess (trader_exec.py)
    pour garantir que toutes les traces sont ecrites dans brain.sqlite.

    Sans cet appel, les daemon threads sont tues a la sortie du process
    et les INSERT ne sont jamais commites.

    Args:
        timeout: secondes max d'attente par thread (defaut 2s)

    Returns:
        nombre de traces effectivement flushees
    """
    with _pending_lock:
        threads = list(_pending_threads)
        _pending_threads.clear()
    flushed = 0
    for th in threads:
        try:
            th.join(timeout=timeout)
            if not th.is_alive():
                flushed += 1
        except Exception:
            pass
    return flushed
