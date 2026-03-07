# === CLI SAFETY PATCH (prepend) ===
import os
import sys

def _cli_safety_precheck():
    # Hard-stop help so run_live never starts anything on --help
    if any(a in sys.argv for a in ("-h", "--help")):
        print("run_live help:\n  --check   Validate env and exit (NO TRADES)\n", flush=True)
        sys.exit(0)

    if "--check" in sys.argv:
        required = ["MODE","TRADER_DRY_RUN","SELL_DRY_RUN","READY_FILE","WALLET_PUBKEY","TRADER_USER_PUBLIC_KEY"]
        missing = [k for k in required if not os.getenv(k)]
        if missing:
            print("❌ missing env: " + ", ".join(missing), flush=True)
            sys.exit(2)
        print("✅ CHECK OK (env present). No trades executed.", flush=True)
        sys.exit(0)

_cli_safety_precheck()
# === END CLI SAFETY PATCH ===

import os

import signal
try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except Exception:
    pass

# --- SELL_ONLY_SKIP_TRADER_LOOP_V1 ---
_MODE = os.getenv("MODE", "").strip().upper()
_SELL_ONLY = (_MODE == "SELL_ONLY")

import sys
import asyncio
import os
from pathlib import Path as _Path

import faulthandler, signal
faulthandler.register(signal.SIGUSR1, all_threads=True)
print("🧯 SIGUSR1 enabled: kill -USR1 <pid> to dump stack", flush=True)
ROOT = str(_Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.sell_engine import SellEngine
from core.positions_db_adapter import PositionsDBAdapter
from core.price_feed_dex import DexScreenerPriceFeed
from src.trader_loop import trader_loop


async def _maybe_await(x):
    if asyncio.iscoroutine(x):
        return await x
    return x


async def main():
    if "--help" in __import__("sys").argv or "-h" in __import__("sys").argv:
        return

    print("🚀 run_live: starting sell_engine + trader_loop", flush=True)

    # Optional: reclaim SOL rent by closing empty token accounts
    if os.getenv("RECLAIM_RENT_ON_START", "0") == "1":
        try:
            import subprocess, time as _time
            print("🧹 RECLAIM_RENT_ON_START=1 -> closing empty token accounts (rent reclaim)", flush=True)
            subprocess.run(["python","-u","scripts/reclaim_rent.py"], check=False)
            _time.sleep(0.5)
        except Exception as e:
            print(f"⚠️ reclaim_rent failed: {e}", flush=True)

    db_path = os.getenv("DB_PATH", "state/trades.sqlite")
    db = PositionsDBAdapter(db_path)

    price_feed = DexScreenerPriceFeed()
    try:
        sell_engine = SellEngine(db=db, price_feed=price_feed)
    except TypeError:
        # compat old SellEngine signature: (db, price_feed, trader)
        sell_engine = SellEngine(db=db, price_feed=price_feed, trader=None)
    print("✅ sell_engine: using step loop SellEngine.run_once()", flush=True)

    sleep_s = float(os.getenv("LOOP_SLEEP_S", "10"))
    # --- SELL_ONLY mode (skip trader_loop) ---
    if os.getenv("SELL_ONLY","0") == "1":
        print("🛑 SELL_ONLY=1 -> sell_engine ONLY (skip trader_loop)", flush=True)
        while True:
            print("💰 SELL_TICK: running sell_engine.run_once()", flush=True)
            try:
                sell_engine.run_once()
                if os.getenv("ONE_SHOT","0")=="1" or os.getenv("SELL_ONE_SHOT","0")=="1":
                    print("🧪 ONE_SHOT=1 -> stop after 1 SELL_TICK", flush=True)
                    return
            except Exception as err:
                print("❌ sell_engine tick error: " + str(err), flush=True)
            await asyncio.sleep(sleep_s)
    # --- end SELL_ONLY ---
    one_shot = os.getenv("ONE_SHOT", "0") in ("1", "true", "True")

    while True:
        print("💰 SELL_TICK: running sell_engine.run_once()", flush=True)
        try:
            # SellEngine est sync -> pas besoin d'await
            sell_engine.run_once()
        except Exception as err:
            print("❌ sell_engine tick error: " + str(err), flush=True)

        print("🧠 trader_loop (universe_builder -> exec -> sign -> send)", flush=True)
        try:
            # trader_loop peut être sync ou async -> safe
            if _SELL_ONLY:
                print('🛑 MODE=SELL_ONLY -> skip trader_loop', flush=True)
            else:
                rc = await _maybe_await(trader_loop())
                if isinstance(rc, int) and rc != 0:
                    raise SystemExit(rc)
        except Exception as err:
            print("❌ trader_loop error: " + str(err), flush=True)

        # NOTE: trader_loop a son propre TRADER_ONE_SHOT.
        # ONE_SHOT ici ne sert que si tu utilises run_live comme loop unique.
        if one_shot:
            break

        await asyncio.sleep(sleep_s)


if __name__ == "__main__":
    asyncio.run(main())
