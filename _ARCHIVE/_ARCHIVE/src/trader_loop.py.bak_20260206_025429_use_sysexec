import argparse, json
import asyncio
import os
import sys
import time
import subprocess
from pathlib import Path

def _parse_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sell-json", default=None)
    ap.add_argument("--buy-json", default=None)
    return ap.parse_args()
async def trader_loop():
    sleep_s = float(os.getenv("LOOP_SLEEP_S", os.getenv("SCAN_INTERVAL_SECONDS", "12")))
    max_trades_per_hour = int(os.getenv("LOOP_MAX_TRADES_PER_HOUR", "6"))
    cooldown_s = int(os.getenv("LOOP_COOLDOWN_MINT_S", "1800"))

    one_shot = os.getenv("TRADER_ONE_SHOT", "0").strip().lower() in ("1","true","yes","on")

    print("🧠 trader_loop (universe_builder -> exec -> sign -> send)", flush=True)
    print("   sleep_s=", sleep_s, "max_trades/h=", max_trades_per_hour, "cooldown_s=", cooldown_s, flush=True)

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH","")

    while True:
        try:
            subprocess.run(
                [sys.executable, "-u", "src/trader_exec.py"],
                check=False,
                env=env,
            )
        except Exception as e:
            print("❌ trader_loop cannot run trader_exec:", e, flush=True)

        if one_shot:
            print("🧪 ONE_SHOT=1 -> stop after one iteration", flush=True)
            return

        await asyncio.sleep(sleep_s)
def main():
    args = _parse_cli()
    if args.sell_json:
        req = json.loads(args.sell_json)
        if "run_sell" in globals():
            return globals()["run_sell"](req)
        if "handle_sell" in globals():
            return globals()["handle_sell"](req)
        print("[trader_loop] SELL request:", req)
        return 0
    if args.buy_json:
        req = json.loads(args.buy_json)
        if "run_buy" in globals():
            return globals()["run_buy"](req)
        if "handle_buy" in globals():
            return globals()["handle_buy"](req)
        print("[trader_loop] BUY request:", req)
        return 0
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
