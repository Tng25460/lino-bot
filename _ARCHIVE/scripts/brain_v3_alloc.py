import json
from pathlib import Path

BASE = 0.0025
stats_file = Path("state/brain_v3_stats.json")

if not stats_file.exists():
    print("No brain stats")
    raise SystemExit(0)

stats = json.loads(stats_file.read_text(encoding="utf-8", errors="ignore") or "{}")
pump = stats.get("PUMP", {}) or {}
normal = stats.get("NORMAL", {}) or {}

pump_wr = float(pump.get("winrate_pct", 0) or 0)
normal_wr = float(normal.get("winrate_pct", 0) or 0)

pump_factor = 1.0
normal_factor = 1.0

if pump_wr > 60:
    pump_factor = 1.5
elif pump_wr < 40:
    pump_factor = 0.6

if normal_wr > 70:
    normal_factor = 1.6
elif normal_wr < 40:
    normal_factor = 0.7

alloc = {
    "PUMP": round(BASE * pump_factor, 6),
    "NORMAL": round(BASE * normal_factor, 6),
}

Path("state/brain_v3_alloc.json").write_text(json.dumps(alloc, indent=2), encoding="utf-8")
print("ALLOC:", alloc)
