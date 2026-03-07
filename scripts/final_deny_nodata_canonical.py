import json, os
from pathlib import Path

MIN_LIQ_USD = float(os.getenv("MIN_LIQ_USD", "1000"))
MIN_TX5M    = int(os.getenv("MIN_TX_5M", "3"))
MIN_VOL5M   = float(os.getenv("MIN_VOL_5M_USD", "200"))

inp = Path("state/READY_CANONICAL.jsonl")
tmp = Path("state/READY_CANONICAL.jsonl.tmp")

def fnum(x, d=0.0):
    try: return float(x)
    except: return d

def inum(x, d=0):
    try: return int(x)
    except: return d

kept = dropped = 0
with inp.open() as f, tmp.open("w") as g:
    for line in f:
        line=line.strip()
        if not line:
            continue
        try:
            o=json.loads(line)
        except Exception:
            continue

        if o.get("ds_ok") is not True:
            dropped += 1
            continue

        liq = fnum(o.get("liquidity_usd"), 0.0)
        tx5 = inum(o.get("txns_5m"), 0)
        v5  = fnum(o.get("vol_5m"), 0.0)

        if liq < MIN_LIQ_USD or tx5 < MIN_TX5M or v5 < MIN_VOL5M:
            dropped += 1
            continue

        g.write(json.dumps(o, ensure_ascii=False) + "\n")
        kept += 1

tmp.replace(inp)
print(f"[READY] final_deny_nodata: kept={kept} dropped={dropped}")
