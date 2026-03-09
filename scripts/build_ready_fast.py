#!/usr/bin/env python3
"""
build_ready_fast.py — Pipeline READY autonome tout-en-un
=========================================================

Genere un fichier ready_to_trade en une seule commande :
1. Fetch candidats depuis Jupiter (toptraded + toptrending)
2. Enrichissement DexScreener (liq, vol, MC, price)
3. Scoring rapide (liq + vol + txns + trend)
4. Ecriture JSONL dans state/ready_scored.jsonl

Usage:
  python scripts/build_ready_fast.py

  # Avec limites personnalisees
  READY_LIMIT=100 READY_MIN_LIQ=5000 python scripts/build_ready_fast.py

  # Ecrire dans un fichier specifique
  READY_OUT=state/ready_scored_tradable.jsonl python scripts/build_ready_fast.py

Env vars:
  READY_OUT         : fichier de sortie (default: state/ready_scored.jsonl)
  READY_LIMIT       : max tokens a enrichir (default: 150)
  READY_MIN_LIQ     : liquidite min USD (default: 3000)
  READY_MIN_VOL24   : volume 24h min USD (default: 1000)
  READY_MIN_TX_5M   : txns 5min min (default: 3)
  DS_TIMEOUT        : DexScreener timeout (default: 5)
  DS_SLEEP          : sleep entre appels DS (default: 0.15)
  JUP_BASE_URL      : Jupiter API base (default: https://lite-api.jup.ag)

Securite:
  - Aucune modification de DB
  - Ecriture atomique (tempfile + rename)
  - Fail-open: si Jupiter/DexScreener down, pas de crash
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# --- Config ---
READY_OUT = os.getenv("READY_OUT", "state/ready_scored.jsonl")
READY_LIMIT = int(os.getenv("READY_LIMIT", "150"))
MIN_LIQ = float(os.getenv("READY_MIN_LIQ", "3000"))
MIN_VOL24 = float(os.getenv("READY_MIN_VOL24", "1000"))
MIN_TX_5M = int(os.getenv("READY_MIN_TX_5M", "3"))
DS_TIMEOUT = float(os.getenv("DS_TIMEOUT", "5"))
DS_SLEEP = float(os.getenv("DS_SLEEP", "0.15"))
JUP_BASE = os.getenv("JUP_BASE_URL", "https://lite-api.jup.ag").rstrip("/")

# Mints a ignorer (stables, WSOL)
IGNORE_MINTS = {
    "So11111111111111111111111111111111111111112",    # WSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",    # USDT
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",     # mSOL
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj",    # stSOL
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",     # bSOL
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",    # JitoSOL
}


def fetch_jupiter_candidates() -> List[Dict[str, Any]]:
    """Fetch depuis Jupiter trending + toptraded."""
    import requests
    candidates = {}

    feeds = [
        f"{JUP_BASE}/tokens/v1/tagged/pump",
        f"{JUP_BASE}/tokens/v1/tagged/lst",
    ]

    # Aussi essayer les nouveaux endpoints
    alt_feeds = [
        "https://tokens.jup.ag/tokens?tags=verified",
        "https://tokens.jup.ag/tokens?tags=community",
    ]

    all_feeds = feeds + alt_feeds

    for url in all_feeds:
        try:
            r = requests.get(url, timeout=10.0, headers={"Accept": "application/json"})
            if r.status_code != 200:
                print(f"  ⚠️ Jupiter {url.split('/')[-1]} http={r.status_code}")
                continue
            data = r.json()
            if isinstance(data, list):
                for item in data:
                    mint = ""
                    if isinstance(item, str):
                        mint = item
                    elif isinstance(item, dict):
                        mint = str(item.get("address", "") or item.get("mint", ""))
                    mint = mint.strip()
                    if mint and mint not in IGNORE_MINTS and len(mint) >= 32:
                        if mint not in candidates:
                            candidates[mint] = {"mint": mint}
                            if isinstance(item, dict):
                                candidates[mint]["symbol"] = str(item.get("symbol", ""))[:20]
                                candidates[mint]["name"] = str(item.get("name", ""))[:50]
            print(f"  ✅ Jupiter {url.split('/')[-1]}: +{len(data) if isinstance(data, list) else 0} tokens")
        except Exception as e:
            print(f"  ⚠️ Jupiter {url.split('/')[-1]}: {e}")

    # Fallback: si aucun token, essayer le tokenlist basique
    if len(candidates) < 10:
        try:
            r = requests.get("https://token.jup.ag/strict", timeout=15.0)
            if r.status_code == 200:
                data = r.json()
                for item in data[:500]:  # top 500
                    mint = str(item.get("address", "")).strip()
                    if mint and mint not in IGNORE_MINTS and len(mint) >= 32:
                        if mint not in candidates:
                            candidates[mint] = {
                                "mint": mint,
                                "symbol": str(item.get("symbol", ""))[:20],
                                "name": str(item.get("name", ""))[:50],
                            }
                print(f"  ✅ Jupiter strict tokenlist: +{min(500, len(data))} tokens")
        except Exception as e:
            print(f"  ⚠️ Jupiter strict tokenlist: {e}")

    result = list(candidates.values())[:READY_LIMIT * 2]  # extra pour filtrage
    print(f"  📊 Total unique mints: {len(result)}")
    return result


def enrich_dexscreener(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Enrichit chaque candidat via DexScreener."""
    import requests
    enriched = []
    total = min(len(candidates), READY_LIMIT)
    print(f"\n🔍 Enrichissement DexScreener ({total} tokens)...")

    for i, cand in enumerate(candidates[:READY_LIMIT]):
        mint = cand.get("mint", "")
        if not mint:
            continue

        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            r = requests.get(url, timeout=DS_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                pairs = data.get("pairs") or []
                if pairs:
                    best = pairs[0]
                    liq_usd = float(best.get("liquidity", {}).get("usd", 0) or 0)
                    mc = float(best.get("marketCap", 0) or 0)
                    vol = best.get("volume", {})
                    txns = best.get("txns", {})
                    chg = best.get("priceChange", {})

                    cand["liquidity_usd"] = liq_usd
                    cand["market_cap_usd"] = mc
                    cand["price_usd"] = float(best.get("priceUsd", 0) or 0)
                    cand["fdv"] = float(best.get("fdv", 0) or 0)
                    cand["vol_5m"] = float(vol.get("m5", 0) or 0)
                    cand["vol_1h"] = float(vol.get("h1", 0) or 0)
                    cand["vol_24h"] = float(vol.get("h24", 0) or 0)
                    cand["tx_5m_buys"] = int(txns.get("m5", {}).get("buys", 0) or 0)
                    cand["tx_5m_sells"] = int(txns.get("m5", {}).get("sells", 0) or 0)
                    cand["tx_5m"] = cand["tx_5m_buys"] + cand["tx_5m_sells"]
                    cand["tx_1h_buys"] = int(txns.get("h1", {}).get("buys", 0) or 0)
                    cand["tx_1h_sells"] = int(txns.get("h1", {}).get("sells", 0) or 0)
                    cand["chg_5m"] = float(chg.get("m5", 0) or 0)
                    cand["chg_1h"] = float(chg.get("h1", 0) or 0)
                    cand["chg_24h"] = float(chg.get("h24", 0) or 0)
                    cand["dex_id"] = str(best.get("dexId", ""))
                    cand["pair_address"] = str(best.get("pairAddress", ""))
                    cand["ds_ok"] = True

                    if not cand.get("symbol"):
                        cand["symbol"] = str(best.get("baseToken", {}).get("symbol", ""))

                    enriched.append(cand)

                    if (i + 1) % 20 == 0:
                        print(f"  [{i+1}/{total}] enriched ({len(enriched)} ok)")
            elif r.status_code == 429:
                print(f"  ⚠️ [{i+1}/{total}] DexScreener 429 rate limit — sleeping 2s")
                time.sleep(2.0)
        except Exception as e:
            if (i + 1) % 50 == 0:
                print(f"  ⚠️ [{i+1}/{total}] DexScreener error: {e}")

        time.sleep(DS_SLEEP)

    print(f"  📊 Enriched: {len(enriched)}/{total}")
    return enriched


def score_candidate(cand: Dict[str, Any]) -> float:
    """Score rapide 0-5 pour triage."""
    s = 0.0
    try:
        liq = float(cand.get("liquidity_usd", 0))
        if liq > 0:
            s += min(1.0, math.log10(1.0 + liq) / 6.0)
    except Exception:
        pass
    try:
        vol24 = float(cand.get("vol_24h", 0))
        if vol24 > 0:
            s += min(1.0, math.log10(1.0 + vol24) / 7.0)
    except Exception:
        pass
    try:
        tx = int(cand.get("tx_5m", 0))
        if tx > 0:
            s += min(0.8, math.log10(1.0 + tx) / 3.0)
    except Exception:
        pass
    try:
        chg = float(cand.get("chg_1h", 0))
        s += max(-0.3, min(0.5, chg / 100.0))
    except Exception:
        pass
    try:
        if cand.get("dex_id"):
            s += 0.05
    except Exception:
        pass
    return max(0.0, round(s, 4))


def filter_and_score(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filtre + score + tri."""
    filtered = []
    for cand in candidates:
        liq = float(cand.get("liquidity_usd", 0))
        vol24 = float(cand.get("vol_24h", 0))
        tx5m = int(cand.get("tx_5m", 0))

        if liq < MIN_LIQ:
            continue
        if vol24 < MIN_VOL24:
            continue
        if tx5m < MIN_TX_5M:
            continue

        cand["score"] = score_candidate(cand)
        filtered.append(cand)

    # Tri par score decroissant
    filtered.sort(key=lambda x: float(x.get("score", 0)), reverse=True)
    print(f"\n📊 Après filtrage: {len(filtered)} candidats (min_liq={MIN_LIQ}, min_vol24={MIN_VOL24}, min_tx5m={MIN_TX_5M})")
    return filtered


def write_jsonl(candidates: List[Dict[str, Any]], path: str) -> int:
    """Ecriture atomique JSONL."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(prefix=".ready_", suffix=".jsonl", dir=str(out.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for cand in candidates:
                f.write(json.dumps(cand, ensure_ascii=False) + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, str(out))
        return len(candidates)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass
        raise


def main():
    print("=" * 60)
    print("BUILD READY FAST — Pipeline tout-en-un")
    print("=" * 60)
    print(f"  Output:    {READY_OUT}")
    print(f"  Limit:     {READY_LIMIT}")
    print(f"  Min liq:   ${MIN_LIQ:,.0f}")
    print(f"  Min vol24: ${MIN_VOL24:,.0f}")
    print(f"  Min tx5m:  {MIN_TX_5M}")
    print()

    # 1. Fetch
    print("📡 Étape 1: Fetch Jupiter candidates...")
    candidates = fetch_jupiter_candidates()
    if not candidates:
        print("❌ Aucun candidat trouvé depuis Jupiter")
        sys.exit(1)

    # 2. Enrich
    enriched = enrich_dexscreener(candidates)
    if not enriched:
        print("❌ Aucun token enrichi (DexScreener down?)")
        sys.exit(1)

    # 3. Filter + Score
    scored = filter_and_score(enriched)
    if not scored:
        print("❌ Aucun token ne passe les filtres")
        print("   Essayer: READY_MIN_LIQ=1000 READY_MIN_VOL24=500 python scripts/build_ready_fast.py")
        sys.exit(1)

    # 4. Write
    n = write_jsonl(scored, READY_OUT)
    print(f"\n✅ {n} candidats écrits dans {READY_OUT}")
    print(f"   Taille: {Path(READY_OUT).stat().st_size:,} bytes")

    # Afficher top 5
    print("\n📋 Top 5 candidats:")
    for i, c in enumerate(scored[:5]):
        sym = c.get("symbol", "?")
        liq = c.get("liquidity_usd", 0)
        vol = c.get("vol_24h", 0)
        mc = c.get("market_cap_usd", 0)
        sc = c.get("score", 0)
        print(f"  {i+1}. {sym:>10}  liq=${liq:>10,.0f}  vol24=${vol:>12,.0f}  MC=${mc:>12,.0f}  score={sc:.3f}")

    # Commande de vérification
    print(f"\nVérification:")
    print(f"  wc -l {READY_OUT}")
    print(f"  head -1 {READY_OUT} | python3 -m json.tool")


if __name__ == "__main__":
    main()
