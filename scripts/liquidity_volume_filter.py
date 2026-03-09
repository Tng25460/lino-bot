#!/usr/bin/env python3
import sys, json, os

raw = sys.stdin.read().strip()
if not raw:
    sys.exit(0)

try:
    j = json.loads(raw)
except Exception:
    sys.exit(0)

# Pas encore enrichi → on laisse passer
if "liquidity_usd" not in j and "volume_5m_usd" not in j:
    print(json.dumps(j))
    sys.exit(0)

profile = j.get("profile", "PUMP")

liq = float(j.get("liquidity_usd", 0))
vol = float(j.get("volume_5m_usd", 0))
tx  = int(j.get("tx_5m", 0))

min_liq = float(os.getenv("MIN_LIQ_USD_PUMP", "0")) if profile == "PUMP" else float(os.getenv("MIN_LIQ_USD_STABLE", "0"))

if liq < min_liq:
    sys.exit(1)

if vol < float(os.getenv("MIN_VOL_5M_USD", "0")):
    sys.exit(1)

if tx < int(os.getenv("MIN_TX_5M", "0")):
    sys.exit(1)

print(json.dumps(j))
