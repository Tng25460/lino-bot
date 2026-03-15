#!/usr/bin/env python3
from __future__ import annotations
import json, pathlib, re, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOGDIR = ROOT / "logs"
OUT = ROOT / "state" / "active_exposure.json"

logs = sorted(LOGDIR.glob("run_live_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
if not logs:
    print("NO_LOG_FOUND")
    raise SystemExit(0)

log = logs[0]
txt = log.read_text(errors="ignore")

pairs = re.findall(r"\[DBG\] loop item mint=([A-Za-z0-9]+)\s+qty=([0-9.eE+-]+)", txt)
seen = {}
for mint, qty in pairs:
    try:
        q = float(qty)
    except Exception:
        q = 0.0
    if q > 0:
        seen[mint] = q

now = int(time.time())

# FORMAT VOLONTAIREMENT SIMPLE/FLAT
# beaucoup plus probable que le lecteur d'exposure compte une liste d'objets OPEN
rows = []
for mint, qty in sorted(seen.items()):
    rows.append({
        "mint": mint,
        "qty": qty,
        "amount": qty,
        "status": "OPEN",
        "opened_ts": now,
        "updated_ts": now,
        "source": "sell_engine_log_resync"
    })

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(rows, indent=2) + "\n")

print(f"RESYNC_OK count={len(rows)} log={log}")
for r in rows:
    print(f"  {r['mint']} qty={r['qty']}")
