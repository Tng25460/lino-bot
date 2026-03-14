"""
P3: Candidate Merger — fusion READY + onchain → READY_CANONICAL.jsonl
=====================================================================

Fusionne deux sources de candidats :
  1. Pipeline READY classique (state/ready_scored.jsonl)
  2. Pipeline onchain_detector (brain.sqlite → onchain_candidates)

Produit un fichier unifié : state/READY_CANONICAL.jsonl
triépar score_final decroissant, prêt a être consommé par trader_exec.

Scoring unifié (0-100):
  - Fraicheur (0-25): tokens recents favorisés
  - Liquidité (0-20): sweet spot 5k-100k USD
  - Route Jupiter (0-15): tradable = bonus, not_tradable = malus
  - Impact (0-10): faible price impact = bonus
  - Activité (0-15): tx velocity, volume 5m/1h
  - Risque (0-15): dev reputation, freeze, concentration

Filtres de sécurité:
  - Pas de stablecoins (USDC, USDT, DAI, mSOL, bSOL, stSOL, JitoSOL)
  - Pas de tokens sans mint valide
  - Pas de tokens avec freeze authority active (si détecté)
  - Dedup par mint (garde le meilleur score)

Usage:
  python -m core.candidate_merger

  # Avec config custom
  MERGER_MIN_SCORE=20 MERGER_MAX_AGE_SEC=600 python -m core.candidate_merger

Env vars:
  MERGER_READY_FILE    : source READY (default: state/ready_scored.jsonl)
  MERGER_ONCHAIN_DB    : brain.sqlite path (default: state/brain.sqlite)
  MERGER_OUT           : sortie (default: state/READY_CANONICAL.jsonl)
  MERGER_MIN_SCORE     : score minimum pour inclusion (default: 10)
  MERGER_MAX_AGE_SEC   : age max onchain candidates (default: 900 = 15min)
  MERGER_MIN_LIQ_USD   : liquidite min USD (default: 2000)
  MERGER_MAX_CANDIDATES : max candidats dans le fichier (default: 100)
  MERGER_ONCHAIN_WINDOW : fenetre onchain en secondes (default: 900)

Sécurité:
  - Aucune modification de DB (lecture seule)
  - Ecriture atomique (tempfile + rename)
  - Fail-open: si une source down, l'autre suffit
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# ============================================================
# Configuration
# ============================================================
READY_FILE = os.getenv("MERGER_READY_FILE",
    os.getenv("READY_SCORED_FILE",
    os.getenv("READY_FILE", "state/ready_scored.jsonl")))
ONCHAIN_DB = os.getenv("MERGER_ONCHAIN_DB",
    os.getenv("BRAIN_DB_PATH",
    os.getenv("BRAIN_DB", "state/brain.sqlite")))
OUT_FILE = os.getenv("MERGER_OUT", "state/READY_CANONICAL.jsonl")
MIN_SCORE = float(os.getenv("MERGER_MIN_SCORE", "10"))
MAX_AGE_SEC = int(os.getenv("MERGER_MAX_AGE_SEC", "900"))
MIN_LIQ_USD = float(os.getenv("MERGER_MIN_LIQ_USD", "2000"))
MAX_CANDIDATES = int(os.getenv("MERGER_MAX_CANDIDATES", "100"))
ONCHAIN_WINDOW = int(os.getenv("MERGER_ONCHAIN_WINDOW", "900"))

# P8: prix SOL estimé (configurable) pour conversion liq_sol → USD
ESTIMATED_SOL_USD = float(os.getenv("MERGER_SOL_PRICE_USD", "150.0"))

# Mints systeme a ignorer (stables, LSTs, wrapped assets)
IGNORE_MINTS: Set[str] = {
    "So11111111111111111111111111111111111111112",      # WSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",    # USDT
    "EchesyfXePKdLtoiZSL9pMFENMHUBkPucZostcXY69sSL",  # DAI (Wormhole)
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",   # mSOL
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj",   # stSOL
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",   # bSOL
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # JitoSOL
    "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",  # WETH (Wormhole)
    "A9mUU4qviSctJVPJdBYWbLfJ32aXvWETBGpPG2sJUAkR",  # USDY
}


# ============================================================
# Loader: READY pipeline (JSONL)
# ============================================================

def load_ready_candidates() -> List[Dict[str, Any]]:
    """Charge les candidats depuis le fichier READY JSONL."""
    candidates = []
    try:
        p = Path(READY_FILE)
        if not p.exists():
            # Fallback: essayer aussi ready_to_trade.jsonl
            for alt in ["state/ready_scored.jsonl", "state/ready_to_trade.jsonl",
                        "ready_to_trade.jsonl", "ready_scored.jsonl"]:
                pa = Path(alt)
                if pa.exists() and pa.stat().st_size > 10:
                    p = pa
                    break
            else:
                return []

        with p.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        mint = str(obj.get("mint", obj.get("address", obj.get("outputMint", "")))).strip()
                        if mint and len(mint) >= 32 and mint not in IGNORE_MINTS:
                            obj["_source"] = "ready"
                            obj["_mint"] = mint
                            candidates.append(obj)
                except Exception:
                    continue
    except Exception as e:
        try:
            print(f"  ⚠️ merger: load_ready failed: {e}", flush=True)
        except Exception:
            pass
    return candidates


# ============================================================
# Loader: Onchain candidates (brain.sqlite)
# ============================================================

def load_onchain_candidates() -> List[Dict[str, Any]]:
    """Charge les candidats recents depuis brain.sqlite → onchain_candidates."""
    candidates = []
    try:
        if not os.path.exists(ONCHAIN_DB):
            return []

        cutoff = int(time.time()) - ONCHAIN_WINDOW
        con = sqlite3.connect(ONCHAIN_DB, timeout=3.0)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT mint, symbol, source, event_type, liq_sol, market_cap_usd, "
            "volume_5m_usd, holder_count, dev_address, fast_score, fast_explain, "
            "in_ready_file, tx_signature, block_time, details_json, ts "
            "FROM onchain_candidates WHERE ts >= ? ORDER BY fast_score DESC LIMIT 200",
            (cutoff,)
        ).fetchall()
        con.close()

        for row in rows:
            mint = str(row["mint"]).strip()
            if not mint or len(mint) < 32 or mint in IGNORE_MINTS:
                continue

            # Parse details_json
            details = {}
            try:
                details = json.loads(row["details_json"] or "{}")
            except Exception:
                pass

            # Préférer liquidity_usd depuis details_json (valeur DexScreener réelle)
            # Fallback: liq_sol n'est PAS fiable (c'est liquidity.base, pas des SOL)
            _liq_usd_from_details = float(details.get("liquidity_usd", 0) or 0)
            _liq_usd = _liq_usd_from_details if _liq_usd_from_details > 0 else 0.0

            candidates.append({
                "_source": "onchain",
                "_mint": mint,
                "mint": mint,
                "symbol": str(row["symbol"] or ""),
                "source": str(row["source"] or ""),
                "event_type": str(row["event_type"] or ""),
                "liquidity_usd": _liq_usd,
                "market_cap_usd": float(row["market_cap_usd"] or 0),
                "vol_5m": float(row["volume_5m_usd"] or 0),
                "fast_score": float(row["fast_score"] or 0),
                "fast_explain": str(row["fast_explain"] or ""),
                "in_ready_file": int(row["in_ready_file"] or 0),
                "tx_signature": str(row["tx_signature"] or ""),
                "block_time": int(row["block_time"] or 0),
                "ts": int(row["ts"] or 0),
                "details": details,
                "jup_routable": details.get("jup_routable"),
                "jup_price_impact_pct": details.get("jup_price_impact_pct"),
                "jup_reason": details.get("jup_reason"),
            })
    except Exception as e:
        try:
            print(f"  ⚠️ merger: load_onchain failed: {e}", flush=True)
        except Exception:
            pass
    return candidates


# ============================================================
# Scoring unifié
# ============================================================

def compute_unified_score(cand: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score unifié (0-100) pour triage de tous les candidats.

    Composantes:
      1. Fraicheur (0-25)
      2. Liquidité (0-20)
      3. Route Jupiter (0-15)
      4. Price impact (0-10)
      5. Activité/velocity (0-15)
      6. Risque (0-15)
    """
    score = 0.0
    components = {}
    flags = []

    now = int(time.time())

    # 1. Fraicheur (0-25) — tokens recents favorises
    try:
        ts = int(cand.get("ts", cand.get("block_time", 0)) or 0)
        age_sec = (now - ts) if ts > 0 else 9999
        cand["age_seconds"] = age_sec

        if age_sec < 30:
            s = 25.0
        elif age_sec < 60:
            s = 22.0
        elif age_sec < 120:
            s = 18.0
        elif age_sec < 300:
            s = 14.0
        elif age_sec < 600:
            s = 8.0
        elif age_sec < MAX_AGE_SEC:
            s = 4.0
        else:
            s = 1.0
        score += s
        components["freshness"] = round(s, 1)
    except Exception:
        components["freshness"] = 0.0

    # 2. Liquidité (0-20) — sweet spot 5k-100k USD
    try:
        liq = float(cand.get("liquidity_usd", cand.get("liq_usd", 0)) or 0)
        if liq <= 0:
            # Fallback: essayer liq_sol * prix SOL estimé
            liq_sol = float(cand.get("liq_sol", 0) or 0)
            if liq_sol > 0:
                liq = liq_sol * ESTIMATED_SOL_USD  # estimation ~$150/SOL

        if 5_000 <= liq <= 50_000:
            s = 20.0  # sweet spot
        elif 50_000 < liq <= 200_000:
            s = 16.0
        elif 2_000 <= liq < 5_000:
            s = 12.0
        elif liq > 200_000:
            s = 8.0
        elif liq > 0:
            s = 3.0
        else:
            s = 0.0
            flags.append("no_liq")

        if liq < MIN_LIQ_USD and liq > 0:
            flags.append("low_liq")

        score += s
        components["liquidity"] = round(s, 1)
        cand["_liq_usd"] = round(liq, 2)
    except Exception:
        components["liquidity"] = 0.0

    # 3. Route Jupiter (0-15) — tradable via Jupiter = bonus
    try:
        jup_routable = cand.get("jup_routable", cand.get("details", {}).get("jup_routable"))
        if jup_routable is True:
            s = 15.0
            cand["_jupiter_route"] = True
        elif jup_routable is False:
            reason = str(cand.get("jup_reason", cand.get("details", {}).get("jup_reason", "")))
            if "not_tradable" in reason:
                s = -5.0
                flags.append("not_tradable")
            elif "no_route" in reason:
                s = -3.0
                flags.append("no_route")
            else:
                s = -1.0
            cand["_jupiter_route"] = False
        else:
            s = 0.0  # inconnu
            cand["_jupiter_route"] = None
        score += s
        components["jupiter"] = round(s, 1)
    except Exception:
        components["jupiter"] = 0.0

    # 4. Price impact (0-10)
    try:
        impact = float(cand.get("jup_price_impact_pct",
                   cand.get("details", {}).get("jup_price_impact_pct", 999)) or 999)
        cand["_price_impact"] = round(impact, 3)
        if impact < 0.5:
            s = 10.0
        elif impact < 1.0:
            s = 8.0
        elif impact < 3.0:
            s = 5.0
        elif impact < 5.0:
            s = 2.0
        elif impact < 10.0:
            s = 0.0
        else:
            s = -2.0
            flags.append("high_impact")
        score += s
        components["impact"] = round(s, 1)
    except Exception:
        components["impact"] = 0.0

    # 5. Activité / tx velocity (0-15)
    try:
        vol_5m = float(cand.get("vol_5m", cand.get("volume_5m_usd", 0)) or 0)
        vol_1h = float(cand.get("vol_1h", 0) or 0)
        tx_5m = int(cand.get("tx_5m", 0) or 0)

        s = 0.0
        # Volume
        if vol_5m > 50_000:
            s += 8.0
        elif vol_5m > 10_000:
            s += 6.0
        elif vol_5m > 1_000:
            s += 3.0
        elif vol_5m > 0:
            s += 1.0

        # Tx count
        if tx_5m > 50:
            s += 7.0
        elif tx_5m > 20:
            s += 5.0
        elif tx_5m > 5:
            s += 3.0
        elif tx_5m > 0:
            s += 1.0

        s = min(15.0, s)
        score += s
        components["activity"] = round(s, 1)
        cand["_tx_velocity"] = tx_5m
    except Exception:
        components["activity"] = 0.0

    # 6. Risque (0-15, peut etre negatif)
    try:
        s = 7.5  # neutre par defaut
        details = cand.get("details", {}) or {}

        # Dev blacklisted
        if details.get("dev_blacklisted"):
            s = -10.0
            flags.append("dev_blacklisted")
        elif details.get("dev_rugs", 0) > 0:
            s = -5.0
            flags.append("dev_rugged")
        elif details.get("dev_avg_pnl", 0) > 0.1:
            s = 15.0  # dev profitable

        # Freeze authority (si détecté)
        if details.get("freeze_authority") or details.get("has_freeze"):
            s = max(-5.0, s - 10.0)
            flags.append("freeze_auth")

        score += s
        components["risk"] = round(s, 1)
    except Exception:
        components["risk"] = 0.0

    # Bonus: double source (present dans les 2 pipelines)
    try:
        if cand.get("in_ready_file") and cand.get("_source") == "onchain":
            score += 5.0  # bonus convergence
            components["convergence"] = 5.0
        elif cand.get("_source") == "ready" and cand.get("_onchain_also"):
            score += 5.0
            components["convergence"] = 5.0
    except Exception:
        pass

    # P8: garde NaN — si score est NaN (float corruption), forcer 0
    if math.isnan(score) or math.isinf(score):
        score = 0.0

    # Clamp 0-100
    score = max(0.0, min(100.0, score))

    cand["score_total"] = round(score, 1)
    cand["score_components"] = components
    cand["risk_flags"] = flags
    cand["_holders_estimate"] = int(cand.get("holder_count", 0) or 0)

    return cand


# ============================================================
# Merge + dedup + filtrage
# ============================================================

def merge_candidates(
    ready: List[Dict[str, Any]],
    onchain: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Fusionne les candidats des deux sources.
    Dedup par mint: garde le meilleur score.
    Filtre par score minimum et liquidité.
    """
    # Index par mint
    by_mint: Dict[str, Dict[str, Any]] = {}

    # Ready candidates d'abord
    for cand in ready:
        mint = cand.get("_mint", "")
        if not mint:
            continue
        scored = compute_unified_score(cand)
        by_mint[mint] = scored

    # Onchain candidates: merge ou ajouter
    onchain_mints = set()
    for cand in onchain:
        mint = cand.get("_mint", "")
        if not mint:
            continue
        onchain_mints.add(mint)
        scored = compute_unified_score(cand)

        if mint in by_mint:
            # Mark convergence
            by_mint[mint]["_onchain_also"] = True
            # Garder le meilleur score
            if scored["score_total"] > by_mint[mint]["score_total"]:
                scored["_onchain_also"] = True
                scored["_ready_also"] = True
                by_mint[mint] = scored
            else:
                # Enrichir le ready avec des infos onchain si manquantes
                existing = by_mint[mint]
                if not existing.get("jup_routable") and scored.get("jup_routable") is not None:
                    existing["jup_routable"] = scored["jup_routable"]
                    existing["_jupiter_route"] = scored.get("_jupiter_route")
                if not existing.get("jup_price_impact_pct") and scored.get("jup_price_impact_pct"):
                    existing["jup_price_impact_pct"] = scored["jup_price_impact_pct"]
                    existing["_price_impact"] = scored.get("_price_impact")
                existing["_onchain_also"] = True
                # Re-score avec convergence bonus
                existing = compute_unified_score(existing)
                by_mint[mint] = existing
        else:
            by_mint[mint] = scored

    # P9: Filtrage final avec logs de rejet detailles
    result = []
    _reject_reasons = {"low_score": 0, "low_liq": 0, "no_liq": 0, "not_tradable": 0,
                       "blacklisted": 0, "freeze": 0, "accepted": 0}

    for mint, cand in by_mint.items():
        score = cand.get("score_total", 0)
        liq = cand.get("_liq_usd", 0)
        sym = cand.get("symbol", "?")[:10]
        src = cand.get("_source", "?")
        flags = cand.get("risk_flags", [])

        # Filtres d'exclusion avec log de rejet
        if score < MIN_SCORE:
            _reject_reasons["low_score"] += 1
            continue
        # BLOC_E: hard-reject no_liq — candidats sans liquidité ne sont pas buyables
        if "no_liq" in flags or liq <= 0:
            _reject_reasons["no_liq"] += 1
            continue
        if liq < MIN_LIQ_USD:
            _reject_reasons["low_liq"] += 1
            continue
        if "not_tradable" in flags:
            _reject_reasons["not_tradable"] += 1
            continue
        if "dev_blacklisted" in flags:
            _reject_reasons["blacklisted"] += 1
            continue
        if "freeze_auth" in flags:
            _reject_reasons["freeze"] += 1
            continue

        result.append(cand)
        _reject_reasons["accepted"] += 1

    # P9: log diagnostic des rejets
    _total_before = len(by_mint)
    try:
        print(
            f"  🔀 merger filter: total={_total_before} accepted={_reject_reasons['accepted']}"
            f" no_liq={_reject_reasons['no_liq']}"
            f" low_score={_reject_reasons['low_score']}"
            f" low_liq={_reject_reasons['low_liq']}"
            f" not_tradable={_reject_reasons['not_tradable']}"
            f" blacklisted={_reject_reasons['blacklisted']}"
            f" freeze={_reject_reasons['freeze']}",
            flush=True,
        )
    except Exception:
        pass

    # Tri par score decroissant
    result.sort(key=lambda x: float(x.get("score_total", 0)), reverse=True)

    # Limiter
    result = result[:MAX_CANDIDATES]

    return result


# ============================================================
# Ecriture atomique JSONL
# ============================================================

def write_canonical(candidates: List[Dict[str, Any]], path: str = "") -> int:
    """Ecrit le fichier READY_CANONICAL.jsonl de maniere atomique."""
    out_path = path or OUT_FILE
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Nettoyer les champs internes avant ecriture
    clean = []
    for cand in candidates:
        entry = {
            "mint": cand.get("_mint", cand.get("mint", "")),
            "symbol": str(cand.get("symbol", ""))[:20],
            "source": cand.get("_source", "unknown"),
            "score_total": cand.get("score_total", 0),
            "score_components": cand.get("score_components", {}),
            "liquidity_usd": cand.get("_liq_usd", 0),
            "market_cap_usd": float(cand.get("market_cap_usd", 0) or 0),
            "age_seconds": cand.get("age_seconds", 0),
            "jupiter_route": cand.get("_jupiter_route"),
            "price_impact_estimate": cand.get("_price_impact", None),
            "tx_velocity": cand.get("_tx_velocity", 0),
            "holders_estimate": cand.get("_holders_estimate", 0),
            "risk_flags": cand.get("risk_flags", []),
            "vol_5m": float(cand.get("vol_5m", cand.get("volume_5m_usd", 0)) or 0),
            "vol_1h": float(cand.get("vol_1h", 0) or 0),
            "vol_24h": float(cand.get("vol_24h", 0) or 0),
            "onchain_also": bool(cand.get("_onchain_also")),
            "ready_also": bool(cand.get("_ready_also", cand.get("in_ready_file", 0))),
            "ts": int(time.time()),
        }
        # Garder les champs du ready original utiles pour trader_exec
        for k in ("outputMint", "address", "amount_lamports", "score",
                   "tx_5m_buys", "tx_5m_sells", "chg_5m", "chg_1h", "chg_24h",
                   "dex_id", "pair_address", "price_usd", "fdv"):
            if k in cand:
                entry[k] = cand[k]

        clean.append(entry)

    # Ecriture atomique
    fd, tmp = tempfile.mkstemp(prefix=".canonical_", suffix=".jsonl", dir=str(out.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for entry in clean:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, str(out))
        return len(clean)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass
        raise


# ============================================================
# Pipeline principal
# ============================================================

def run_merge() -> int:
    """Execute le merge complet. Retourne le nombre de candidats ecrits."""
    t0 = time.time()

    # 1. Charger les sources
    ready = load_ready_candidates()
    onchain = load_onchain_candidates()

    print(f"  📡 Sources: ready={len(ready)} onchain={len(onchain)}", flush=True)

    if not ready and not onchain:
        print("  ⚠️ Aucun candidat (ready=0, onchain=0)", flush=True)
        return 0

    # 2. Fusionner
    merged = merge_candidates(ready, onchain)
    print(f"  🔀 Merged: {len(merged)} candidats (score>={MIN_SCORE}, liq>=${MIN_LIQ_USD})", flush=True)

    if not merged:
        print("  ⚠️ Aucun candidat après fusion/filtrage", flush=True)
        return 0

    # 3. Ecrire
    n = write_canonical(merged)
    elapsed = time.time() - t0

    print(f"  ✅ {n} candidats écrits dans {OUT_FILE} ({elapsed:.1f}s)", flush=True)

    # Afficher top 5
    print(f"\n  📋 Top 5:", flush=True)
    for i, c in enumerate(merged[:5]):
        mint = c.get("_mint", c.get("mint", ""))[:8]
        sym = c.get("symbol", "?")
        sc = c.get("score_total", 0)
        liq = c.get("_liq_usd", 0)
        src = c.get("_source", "?")
        jup = "✓" if c.get("_jupiter_route") else ("✗" if c.get("_jupiter_route") is False else "?")
        flags = ",".join(c.get("risk_flags", [])) or "-"
        print(f"    {i+1}. {sym:>10} ({mint}…) score={sc:.0f} liq=${liq:,.0f} src={src} jup={jup} flags={flags}", flush=True)

    return n


# ============================================================
# CLI
# ============================================================

def main():
    print("=" * 60)
    print("CANDIDATE MERGER — Fusion READY + Onchain")
    print("=" * 60)
    print(f"  Ready file:   {READY_FILE}")
    print(f"  Onchain DB:   {ONCHAIN_DB}")
    print(f"  Output:       {OUT_FILE}")
    print(f"  Min score:    {MIN_SCORE}")
    print(f"  Min liq USD:  ${MIN_LIQ_USD:,.0f}")
    print(f"  Max age:      {MAX_AGE_SEC}s")
    print(f"  Max output:   {MAX_CANDIDATES}")
    print()

    n = run_merge()
    if n == 0:
        print("❌ Aucun candidat produit")
        sys.exit(1)

    print(f"\n✅ Merge terminé: {n} candidats")
    print(f"\nVérification:")
    print(f"  wc -l {OUT_FILE}")
    print(f"  head -1 {OUT_FILE} | python3 -m json.tool")


if __name__ == "__main__":
    main()
