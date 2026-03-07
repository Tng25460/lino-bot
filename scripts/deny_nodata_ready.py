import sys, json, os

MIN_LIQ_USD = float(os.getenv("MIN_LIQ_USD", "1000"))
MIN_TX5M    = int(os.getenv("MIN_TX_5M", "3"))
MIN_VOL5M   = float(os.getenv("MIN_VOL_5M_USD", "200"))

def fnum(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d

def inum(x, d=0):
    try:
        return int(x)
    except Exception:
        return d

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        o = json.loads(line)
    except Exception:
        continue

    # must have real data
    if o.get("ds_ok") is not True:
        continue

    liq = fnum(o.get("liquidity_usd"), 0.0)
    tx5 = inum(o.get("txns_5m"), 0)
    v5  = fnum(o.get("vol_5m"), 0.0)

    if liq < MIN_LIQ_USD:
        continue
    if tx5 < MIN_TX5M:
        continue
    if v5 < MIN_VOL5M:
        continue

    sys.stdout.write(json.dumps(o, ensure_ascii=False) + "\n")
