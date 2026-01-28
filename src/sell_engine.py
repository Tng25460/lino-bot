from __future__ import annotations

import os
import time
import asyncio
from pathlib import Path

# This file is intentionally conservative: it must NEVER crash run_live.
# We'll plug full TP/SL/trailing logic after stability is restored.

DEFAULT_DB = os.getenv("DB_PATH", "state/trades.sqlite")


def _wallet_pubkey() -> str:
    return (os.getenv("WALLET_PUBKEY") or os.getenv("TRADER_USER_PUBLIC_KEY") or "").strip()


async def _tick(db_path: str, wallet: str) -> None:
    # Minimal check so the loop is alive; no DB writes.
    # Later we’ll implement full sell logic here.
    _ = db_path
    _ = wallet
    await asyncio.sleep(0)


def sell_engine(db_path: str | None = None, *args, **kwargs):
    db_path = db_path or DEFAULT_DB
    wallet = _wallet_pubkey()

    print("✅ sell_engine: clean wrapper started")
    print("   db_path=", db_path)
    if not wallet:
        print("⚠️ sell_engine: missing WALLET_PUBKEY/TRADER_USER_PUBLIC_KEY -> running idle loop")

    # Small step loop
    while True:
        try:
            asyncio.run(_tick(db_path, wallet))
        except Exception as e:
            print("❌ sell_engine tick error:", e)
        time.sleep(float(os.getenv("SELL_ENGINE_SLEEP_S", "2.0")))


# Keep compatibility if someone imports SellEngine symbol
class SellEngine:
    def __init__(self, db_path: str = DEFAULT_DB, wallet: str | None = None):
        self.db_path = db_path
        self.wallet = wallet or _wallet_pubkey()

    async def run_once(self, wallet: str | None = None):
        await _tick(self.db_path, wallet or self.wallet)


if __name__ == "__main__":
    sell_engine()

# --- CLEAN_WRAPPER_V1 ---
def sell_engine(db_path: str = "state/trades.sqlite", *args, **kwargs):
    """
    Thread target used by src/run_live.py.
    It runs SellEngine in the safest compatible way:
      - prefers .run_forever() / .run()
      - else loops .run_once(...) (sync or async)
    Passes wallet as *pubkey string* (not Keypair object).
    """
    import os, time, asyncio, inspect

    from src.sell_engine import SellEngine  # class in this same module

    wallet_pub = (os.getenv("WALLET_PUBKEY") or os.getenv("TRADER_USER_PUBLIC_KEY") or "").strip()
    if not wallet_pub:
        print("❌ sell_engine: missing WALLET_PUBKEY/TRADER_USER_PUBLIC_KEY")
        return

    eng = SellEngine(db_path=db_path, *args, **kwargs)

    # Choose method
    if hasattr(eng, "run_forever") and callable(getattr(eng, "run_forever")):
        print("✅ sell_engine: using SellEngine.run_forever()")
        return eng.run_forever()

    if hasattr(eng, "run") and callable(getattr(eng, "run")):
        print("✅ sell_engine: using SellEngine.run()")
        return eng.run()

    # fallback: step loop with run_once / step
    fn = None
    for name in ("run_once", "step", "loop"):
        if hasattr(eng, name) and callable(getattr(eng, name)):
            fn = getattr(eng, name)
            break

    if fn is None:
        raise AttributeError("SellEngine has no run_forever/run/run_once/step/loop")

    print("✅ sell_engine: using step loop SellEngine.%s()" % fn.__name__)

    async def _call_async(f):
        sig = inspect.signature(f)
        if len(sig.parameters) == 0:
            return await f()
        return await f(wallet_pub)

    def _call_sync(f):
        sig = inspect.signature(f)
        if len(sig.parameters) == 0:
            return f()
        return f(wallet_pub)

    while True:
        try:
            if inspect.iscoroutinefunction(fn):
                asyncio.run(_call_async(fn))
            else:
                _call_sync(fn)
        except Exception as e:
            print("❌ sell_engine step error:", e)
        time.sleep(float(os.getenv("SELL_ENGINE_SLEEP_S", "2.0")))
