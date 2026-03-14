# === ENV LOADING (doit être PREMIER, avant tout os.getenv) ===
import os
import sys

def _load_env_file(path: str = "state/live.env") -> int:
    """Charge state/live.env sans python-dotenv. Ne surcharge PAS les vars déjà définies."""
    loaded = 0
    try:
        if not os.path.exists(path):
            return 0
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                if key and key not in os.environ:
                    os.environ[key] = val
                    loaded += 1
    except Exception:
        pass
    return loaded

_n_env = _load_env_file("state/live.env")
if _n_env > 0:
    print(f"📄 run_live: loaded {_n_env} vars from state/live.env", flush=True)
# Log les vars critiques pour confirmer le chargement
for _k in ("SHADOW_MODE", "ONCHAIN_DETECTOR_ENABLED", "MERGER_ENABLED",
           "TRADER_DRY_RUN", "DRY_RUN"):
    _v = os.environ.get(_k)
    if _v is not None:
        print(f"   {_k}={_v}", flush=True)
# === END ENV LOADING ===

# === CLI SAFETY PATCH (prepend) ===

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

    # SEPARATE_SELL_LOOP_V1: run sell_engine in its own loop so it keeps selling even when trader_loop is slow
    sell_sleep_s = float(os.getenv("SELL_ONLY_SLEEP_S", os.getenv("SELL_LOOP_SLEEP_S", "2")))
    trader_sleep_s = float(os.getenv("TRADER_LOOP_SLEEP_S", os.getenv("LOOP_SLEEP_S", "10")))

    # PHASE2_P2.8: kill switch — fichier state/KILL_SWITCH → arrêt propre des loops
    _KILL_SWITCH_FILE = _Path(os.getenv("KILL_SWITCH_FILE", "state/KILL_SWITCH"))

    def _kill_switch_active() -> bool:
        try:
            return _KILL_SWITCH_FILE.exists()
        except Exception:
            return False

    # PHASE2_P2.9: heartbeat — écrit un timestamp à chaque tick pour monitoring externe
    _HB_DIR = _Path(os.getenv("HEARTBEAT_DIR", "state"))
    def _heartbeat(name: str):
        try:
            import time as _hbt
            _HB_DIR.mkdir(parents=True, exist_ok=True)
            (_HB_DIR / f"heartbeat_{name}.txt").write_text(str(int(_hbt.time())), encoding="utf-8")
        except Exception:
            pass

    async def _sell_loop():
        while True:
            # PHASE2_P2.8: kill switch check
            if _kill_switch_active():
                print("🛑 KILL_SWITCH detected -> sell_loop stopping gracefully", flush=True)
                return
            _heartbeat("sell")  # PHASE2_P2.9
            try:
                print('💰 SELL_TICK (loop)', flush=True)
                sell_engine.run_once()
            except Exception as e:
                import traceback
                print('❌ sell_engine tick error:', repr(e), flush=True)
                traceback.print_exc()
            # ONE_SHOT: stop after 1 tick if requested
            if os.getenv('ONE_SHOT','0') in ('1','true','True') or os.getenv('SELL_ONE_SHOT','0') in ('1','true','True'):
                print('🧪 ONE_SHOT=1 -> stop after 1 SELL_TICK', flush=True)
                return
            await asyncio.sleep(sell_sleep_s)

    async def _trader_loop_runner():
        if _SELL_ONLY or os.getenv('SELL_ONLY','0') == '1':
            print('🛑 SELL_ONLY -> skip trader_loop', flush=True)
            while True:
                if _kill_switch_active():
                    print("🛑 KILL_SWITCH detected -> trader_loop stopping gracefully", flush=True)
                    return
                await asyncio.sleep(trader_sleep_s)
        while True:
            # PHASE2_P2.8: kill switch check
            if _kill_switch_active():
                print("🛑 KILL_SWITCH detected -> trader_loop stopping gracefully", flush=True)
                return
            _heartbeat("buy")  # PHASE2_P2.9
            print('🧠 trader_loop (universe_builder -> exec -> sign -> send)', flush=True)
            try:
                rc = await _maybe_await(trader_loop())
                if isinstance(rc, int) and rc != 0:
                    raise SystemExit(rc)
            except Exception as e:
                import traceback
                print('❌ trader_loop error:', repr(e), flush=True)
                traceback.print_exc()
            if os.getenv('ONE_SHOT','0') in ('1','true','True'):
                return
            await asyncio.sleep(trader_sleep_s)
    
    # PHASE4_P4.8: health monitor loop (non-bloquant, fail-open)
    async def _health_loop():
        _health_interval = float(os.getenv("HEALTH_INTERVAL_SEC", "60"))
        while True:
            if _kill_switch_active():
                return
            try:
                from core.health_monitor import collect_health, write_health_json
                _h = collect_health()
                write_health_json(_h)
            except Exception as _he:
                try:
                    print(f"⚠️ health_monitor tick error: {_he}", flush=True)
                except Exception:
                    pass
            await asyncio.sleep(_health_interval)

    # PHASE5_P5.0: onchain detector shadow loop (OFF par defaut)
    async def _onchain_loop():
        try:
            from core.onchain_detector import onchain_detector_loop
            await onchain_detector_loop()
        except Exception as _oe:
            try:
                print(f"⚠️ onchain_detector loop error: {_oe}", flush=True)
            except Exception:
                pass

    # P3: candidate merger loop (fusionne READY + onchain → READY_CANONICAL)
    async def _merger_loop():
        _merger_interval = float(os.getenv("MERGER_INTERVAL_SEC", "30"))
        _merger_enabled = os.getenv("MERGER_ENABLED", "0").strip().lower() in ("1", "true", "yes")
        if not _merger_enabled:
            print("🔇 candidate_merger: DISABLED (set MERGER_ENABLED=1)", flush=True)
            return
        print(f"🔀 candidate_merger: started (interval={_merger_interval}s)", flush=True)
        while True:
            try:
                from core.candidate_merger import run_merge
                _n = run_merge()
                if _n > 0:
                    print(f"🔀 merger: {_n} candidates → READY_CANONICAL", flush=True)
            except Exception as _me:
                try:
                    print(f"⚠️ candidate_merger error: {_me}", flush=True)
                except Exception:
                    pass
            await asyncio.sleep(_merger_interval)

    # run all loops concurrently (sell + buy + health + onchain shadow + merger)
    await asyncio.gather(
        _sell_loop(),
        _trader_loop_runner(),
        _health_loop(),
        _onchain_loop(),
        _merger_loop(),
    )
if __name__ == "__main__":
    asyncio.run(main())
