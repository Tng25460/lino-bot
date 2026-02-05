import os, sys
from pathlib import Path
import subprocess

ROOT = Path(".")
CRIT = [
  "src/run_live.py",
  "src/trader_exec.py",
  "core/jupiter_exec.py",
  "core/sell_engine.py",
  "scripts/filter_ready_tradable.py",
  "state/skip_mints_trader.txt",
  "state/skip_mints_brain.txt",
]

def main():
    missing = [p for p in CRIT if not (ROOT/p).exists()]
    if missing:
        print("❌ missing critical files:")
        for p in missing: print("  -", p)
    else:
        print("✅ critical files present")

    # compile all py (fast)
    print("🧪 py_compile all...")
    r = subprocess.run([sys.executable, "-m", "compileall", "-q", "."], capture_output=True, text=True)
    if r.returncode == 0:
        print("✅ compileall OK")
    else:
        print("❌ compileall FAIL")
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])

    # env highlights
    keys = [
      "JUP_BASE_URL","TRADER_DRY_RUN","STRICT_ONLY","ROUTE_GATE_MODE",
      "ALLOWED_ROUTE_LABELS","DENY_ROUTE_LABELS",
      "TRADER_SKIP_MINTS_FILE","BRAIN_SKIP_MINTS_FILE",
      "READY_FILE","BRAIN_READY_IN","BRAIN_READY_OUT",
    ]
    print("🔎 env:")
    for k in keys:
        v = os.getenv(k)
        if v is not None:
            print(f"  {k}={v}")

if __name__ == "__main__":
    main()
