#!/usr/bin/env python3
import sys, json, time, random

raw = sys.stdin.read().strip()
if not raw:
    sys.exit(0)

try:
    j = json.loads(raw)
except Exception:
    sys.exit(0)

# --- STUB ENRICH (remplacé plus tard par vraies APIs) ---
j.setdefault("profile", "PUMP")

j.setdefault("liquidity_usd", random.uniform(5_000, 50_000))
j.setdefault("volume_5m_usd", random.uniform(2_000, 20_000))
j.setdefault("tx_5m", random.randint(5, 50))

j.setdefault("has_mint_authority", 0)
j.setdefault("has_freeze_authority", 0)

j.setdefault("top1_pct", random.uniform(5, 40))
j.setdefault("top5_pct", random.uniform(20, 80))

j.setdefault("jup_error", None)
j["enriched_at"] = int(time.time())

print(json.dumps(j))
