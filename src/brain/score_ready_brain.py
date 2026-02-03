#!/usr/bin/env python3
import os, json, time, math

INP = os.getenv("INP", "state/ready_final.capped.jsonl")
OUT = os.getenv("OUT", "state/ready_brain.jsonl")

# SAFE caps (tu peux ajuster)
SAFE_MAX_MCAP = float(os.getenv("SAFE_MAX_MCAP", "2000000"))
SAFE_MIN_LIQ  = float(os.getenv("SAFE_MIN_LIQ",  "3000"))
SAFE_MIN_VOL24 = float(os.getenv("SAFE_MIN_VOL24", "200"))
SAFE_MIN_TX1H = float(os.getenv("SAFE_MIN_TX1H", "2"))

# SCOUT trigger (x10/x100 hunting)
SCOUT_MAX_MCAP = float(os.getenv("SCOUT_MAX_MCAP", "300000"))
SCOUT_MIN_LIQ  = float(os.getenv("SCOUT_MIN_LIQ",  "800"))
SCOUT_MIN_TX5M = float(os.getenv("SCOUT_MIN_TX5M", "6"))
SCOUT_MIN_VOL5M = float(os.getenv("SCOUT_MIN_VOL5M", "50"))
SCOUT_MIN_CHG5M = float(os.getenv("SCOUT_MIN_CHG5M", "2.0"))

def sf(x, d=0.0):
    try:
        if x is None: return d
        return float(x)
    except:
        return d

def clip(x, a, b):
    return max(a, min(b, x))

rows=[]
tot=bad=0

with open(INP,"r",encoding="utf-8") as f:
    for line in f:
        line=line.strip()
        if not line: continue
        tot += 1
        try: j=json.loads(line)
        except: bad += 1; continue

        mint = str(j.get("mint") or "")
        if len(mint) < 20:
            bad += 1
            continue

        liq = sf(j.get("liquidity_usd") or j.get("liq") or 0.0)
        vol24 = sf(j.get("vol_24h") or j.get("vol24") or 0.0)
        vol5 = sf(j.get("vol_5m") or 0.0)
        tx1h = sf(j.get("txns_1h") or j.get("tx1h") or 0.0)
        tx5 = sf(j.get("txns_5m") or 0.0)
        ch5 = sf(j.get("chg_5m") or j.get("chg5m") or 0.0)
        mcap = sf(j.get("market_cap") or j.get("mcap") or 0.0)
        score_used = sf(j.get("score_used") or 0.0)

        # Base score (stabilisé)
        base = score_used

        # “Momentum” doux (évite les traps)
        mom = 0.0
        mom += clip(math.log10(1.0 + vol24), 0.0, 6.0) * 0.08
        mom += clip(tx1h, 0.0, 50.0) * 0.01
        mom += clip(ch5, -10.0, 20.0) * 0.01

        # Penalités
        pen = 0.0
        if liq < SAFE_MIN_LIQ: pen += 0.20
        if vol24 < SAFE_MIN_VOL24: pen += 0.10
        if tx1h < SAFE_MIN_TX1H: pen += 0.10
        if mcap > SAFE_MAX_MCAP and mcap > 0: pen += 0.35

        safe_ok = (liq >= SAFE_MIN_LIQ and vol24 >= SAFE_MIN_VOL24 and tx1h >= SAFE_MIN_TX1H and (mcap <= SAFE_MAX_MCAP or mcap <= 0))

        # SCOUT trigger = microcap + “impulsion” court-terme
        scout_ok = (
            (mcap > 0 and mcap <= SCOUT_MAX_MCAP) and
            (liq >= SCOUT_MIN_LIQ) and
            (tx5 >= SCOUT_MIN_TX5M) and
            (vol5 >= SCOUT_MIN_VOL5M) and
            (ch5 >= SCOUT_MIN_CHG5M)
        )

        mode = "SAFE" if safe_ok else ("SCOUT" if scout_ok else "SKIP")

        # Score final : SAFE favorise la stabilité / SCOUT favorise la micro-impulsion
        final = base + mom - pen
        if mode == "SCOUT":
            final += 0.35
            final += clip(tx5, 0, 60) * 0.008
            final += clip(ch5, 0, 30) * 0.01
            final -= clip(mcap/SCOUT_MAX_MCAP, 0, 3) * 0.08

        j["brain_mode"] = mode
        j["brain_score"] = float(final)
        rows.append(j)

rows.sort(key=lambda x: float(x.get("brain_score") or 0.0), reverse=True)

with open(OUT,"w",encoding="utf-8") as g:
    for j in rows:
        if j.get("brain_mode") == "SKIP":
            continue
        g.write(json.dumps(j, separators=(",",":"))+"\n")

print(f"[OK] brain score: in={INP} total={tot} bad={bad} out={OUT} kept={sum(1 for r in rows if r.get('brain_mode')!='SKIP')}")
