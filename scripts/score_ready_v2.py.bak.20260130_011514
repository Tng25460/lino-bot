#!/usr/bin/env python3
import os, json, time
from pathlib import Path
from collections import Counter

INP  = Path(os.getenv("READY_IN",  "ready_to_trade_enriched.jsonl"))
OUT  = Path(os.getenv("READY_OUT", "ready_to_trade_scored.jsonl"))
TOPN = int(os.getenv("READY_TOPN", "200"))

DEX_ALLOW = set(x.strip() for x in os.getenv("DEX_ALLOW", "raydium").lower().split(",") if x.strip())

# Thresholds (tune via env)
MIN_LIQ_USD  = float(os.getenv("SCORE_MIN_LIQ",  "5000"))
MIN_VOL5_USD = float(os.getenv("SCORE_MIN_VOL5", "100"))
MIN_TX5      = float(os.getenv("SCORE_MIN_TX5",  "2"))
MIN_CHG5     = float(os.getenv("SCORE_MIN_CHG5", "0.5"))
MIN_CHG1H    = float(os.getenv("SCORE_MIN_CHG1H","3.0"))

MAX_FDV      = float(os.getenv("SCORE_MAX_FDV",  "50000000"))
MAX_MCAP     = float(os.getenv("SCORE_MAX_MCAP", "50000000"))

SCORE_MIN    = float(os.getenv("SCORE_MIN",     "3.5"))

READY_STATS  = os.getenv("READY_STATS", "0") == "1"

def _f(x, d=0.0):
    try:
        if x is None:
            return d
        return float(x)
    except Exception:
        return d

def score_row(o: dict):
    dex = (o.get("dex_id") or "").lower().strip()
    if DEX_ALLOW and dex and dex not in DEX_ALLOW:
        return None, "gate_dex", {}

    liq = _f(o.get("liquidity_usd"))
    v5  = _f(o.get("vol_5m"))
    tx5 = _f(o.get("txns_5m"))
    ch5 = _f(o.get("chg_5m"))
    ch1 = _f(o.get("chg_1h"))
    fdv = _f(o.get("fdv"))
    mcp = _f(o.get("market_cap"))

    if liq < MIN_LIQ_USD:  return None, "gate_liq",   {"liq": liq}
    if v5  < MIN_VOL5_USD: return None, "gate_vol5",  {"vol5m": v5}
    if tx5 < MIN_TX5:      return None, "gate_tx5",   {"tx5m": tx5}
    if ch5 < MIN_CHG5:     return None, "gate_chg5",  {"chg5m": ch5}
    if ch1 < MIN_CHG1H:    return None, "gate_chg1h", {"chg1h": ch1}
    if fdv and fdv > MAX_FDV:   return None, "gate_fdv",  {"fdv": fdv}
    if mcp and mcp > MAX_MCAP:  return None, "gate_mcap", {"mcap": mcp}

    # score (bounded / stable)
    s_liq = min(2.0, max(0.0, liq / (MIN_LIQ_USD * 3.0)))       # 0..2
    s_v5  = min(3.0, max(0.0, v5  / (MIN_VOL5_USD * 4.0)))      # 0..3
    s_ch5 = min(3.0, max(0.0, ch5 / 30.0))                      # 0..3
    s_tx  = min(2.0, max(0.0, tx5 / 30.0))                      # 0..2

    score = float(s_liq + s_v5 + s_ch5 + s_tx)

    dbg = {
        "liq": liq, "vol5m": v5, "tx5m": tx5, "chg5m": ch5, "chg1h": ch1, "fdv": fdv, "mcap": mcp,
        "s_liq": s_liq, "s_v5": s_v5, "s_ch5": s_ch5, "s_tx": s_tx,
        "score_min": SCORE_MIN,
    }

    if score < SCORE_MIN:
        return None, "gate_scoremin", dbg

    return score, "ok", dbg

def main():
    if not INP.exists():
        raise SystemExit(f"missing {INP}")

    rows=[]
    total=0
    for line in INP.read_text(encoding="utf-8", errors="ignore").splitlines():
        if total >= TOPN:
            break
        line=line.strip()
        if not line:
            continue
        try:
            o=json.loads(line)
        except Exception:
            continue
        if not isinstance(o, dict):
            continue
        rows.append(o)
        total += 1

    if READY_STATS:
        c=Counter()
        kept=0
        for o in rows:
            sc, reason, _ = score_row(o)
            if sc is None:
                c[reason]+=1
            else:
                kept += 1
                c["ok"] += 1
        print("gate_stats:", dict(c))
        print("kept_ok:", kept, "total:", len(rows))
        return 0

    # write output
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("", encoding="utf-8")

    kept=0
    for o in rows:
        sc, reason, dbg = score_row(o)
        if sc is None:
            continue
        o["score"] = float(sc)
        o["score_reason"] = reason
        o["score_dbg"] = dbg
        o["scored_at"] = int(time.time())
        OUT.open("a", encoding="utf-8").write(json.dumps(o, ensure_ascii=False) + "\n")
        kept += 1

    size = OUT.stat().st_size if OUT.exists() else 0
    print(f"scored: {kept} of {len(rows)} -> {OUT} bytes= {size}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
