"""
PHASE3_P3.3: Filtre unifie des candidats (stablecoins, stocks, mots-cles).

Extrait de src/trader_exec.py (PHASE2_P2.7 ASSET_FILTER_UNIFIED).
Combine: stablecoins deny + stock/action deny + word deny — 1 seul passage.
"""
from __future__ import annotations
import os
from typing import List, Dict, Any


def filter_assets(ready: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filtre les candidats en supprimant stablecoins, stocks tokenises, et mots-cles interdits.
    Configurable via env vars:
      - STABLE_DENY_SYMBOLS: symboles stables a bloquer
      - STABLE_DENY_MINTS: mints specifiques a bloquer
      - ACTION_DENY_SYMBOLS: symboles stocks/actions a bloquer
      - ACTION_DENY_WORDS: mots-cles a bloquer dans symbol+name

    Retourne la liste filtree. En cas d'erreur, retourne la liste originale (fail-open).
    """
    try:
        _before_filter = len(ready)
        _deny_syms = {
            x.strip().upper()
            for x in os.getenv(
                "STABLE_DENY_SYMBOLS",
                "USDC,USDT,DAI,USDE,USD1,PYUSD,FDUSD,USDS,EURC",
            ).split(",")
            if x.strip()
        }
        _deny_mints = {
            x.strip()
            for x in os.getenv("STABLE_DENY_MINTS", "").split(",")
            if x.strip()
        }
        _deny_stock_syms = {
            x.strip().upper()
            for x in os.getenv(
                "ACTION_DENY_SYMBOLS",
                "SPYX,AMZNX,TSLAX,NVDAX,AAPLX,METAX,GOOGLX,NFLXX,COINX,MSTRX",
            ).split(",")
            if x.strip()
        }
        _deny_words = tuple(
            x.strip().upper()
            for x in os.getenv(
                "ACTION_DENY_WORDS",
                "STOCK,SHARE,EQUITY,ETF,NASDAQ,S&P,SP500,NVIDIA,AMAZON,TESLA,APPLE,MICROSOFT,GOOGLE,META,NETFLIX,COINBASE,MICROSTRATEGY,STABLE,USDC,USDT,DAI,USDE,USD1,PYUSD,FDUSD,USDS,EURC",
            ).split(",")
            if x.strip()
        )
        _tmp = []
        for _r in ready:
            try:
                _mint = str(
                    (_r.get("mint") or _r.get("output_mint") or _r.get("address") or "")
                ).strip()
                _sym = str(
                    (_r.get("symbol") or _r.get("ticker") or "")
                ).strip().upper()
                _name = str(
                    (_r.get("name") or _r.get("token_name") or "")
                ).strip().upper()
                _txt = f"{_sym} {_name}"

                _deny = False
                if _mint in _deny_mints:
                    _deny = True
                if _sym in _deny_syms:
                    _deny = True
                if _sym in _deny_stock_syms:
                    _deny = True
                if _sym.endswith("X") and len(_sym) >= 4:
                    _deny = True
                if any(_w in _txt for _w in _deny_words):
                    _deny = True

                if _deny:
                    continue
                _tmp.append(_r)
            except Exception:
                _tmp.append(_r)

        if len(_tmp) != _before_filter:
            print(f"🚫 ASSET_FILTER ready: {_before_filter}->{len(_tmp)}")
        return _tmp
    except Exception as e:
        print(f"⚠️ ASSET_FILTER error: {e}")
        return ready  # fail-open: retourne la liste originale
