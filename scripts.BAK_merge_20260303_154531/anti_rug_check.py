#!/usr/bin/env python3
import sys, json, os

raw = sys.stdin.read().strip()
if not raw:
    sys.exit(0)

try:
    j = json.loads(raw)
except Exception:
    sys.exit(0)

# Champs absents ? → on laisse passer
if "top1_pct" not in j and "has_mint_authority" not in j:
    print(json.dumps(j))
    sys.exit(0)

if int(j.get("has_mint_authority", 0)) and int(os.getenv("REJECT_MINT_AUTH", "1")):
    sys.exit(1)

if int(j.get("has_freeze_authority", 0)) and int(os.getenv("REJECT_FREEZE_AUTH", "1")):
    sys.exit(1)

if float(j.get("top1_pct", 0)) > float(os.getenv("MAX_TOP1_PCT", "100")):
    sys.exit(1)

if float(j.get("top5_pct", 0)) > float(os.getenv("MAX_TOP5_PCT", "100")):
    sys.exit(1)

print(json.dumps(j))
