#!/usr/bin/env python3
import os, sys, time, sqlite3, traceback, inspect

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)

DB_PATH = os.getenv("TRADES_DB", "state/trades.sqlite")

class StubPriceFeed:
    """
    PriceFeed minimal pour tests FORCE_SELL_ALL / SIMULATE_MAP.
    Fournit des méthodes sync/async au cas où sell_engine en appelle une.
    """
    def get_price(self, mint: str):
        return None

    def get_price_usd(self, mint: str):
        return None

    async def aget_price(self, mint: str):
        return None

    async def aget_price_usd(self, mint: str):
        return None

def _count_open():
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    n = cur.execute("SELECT COUNT(*) FROM positions WHERE close_ts IS NULL").fetchone()[0]
    con.close()
    return n

def main():
    print("----- SELL_ENGINE_ONCE -----", flush=True)
    print("[cwd]", os.getcwd(), flush=True)
    print("[db ]", DB_PATH, flush=True)
    print("[env] SELL_WRAP_SIMULATE_MAP=", os.getenv("SELL_WRAP_SIMULATE_MAP"), flush=True)

    from core.positions_db_adapter import PositionsDBAdapter
    from core.sell_engine import SellEngine

    # show signature (debug)
    try:
        print("[SellEngine.__init__]", inspect.signature(SellEngine.__init__), flush=True)
    except Exception:
        pass

    db = PositionsDBAdapter(DB_PATH)
    pf = StubPriceFeed()

    # constructeur canonique
    eng = SellEngine(db, pf)

    before = _count_open()
    print("[open_positions_before]", before, flush=True)

    # 1 tick
    try:
        out = eng.run_once()
        print("[run_once_return]", out, flush=True)
    except Exception as e:
        print("[EXC] run_once:", repr(e), flush=True)
        traceback.print_exc()
        return 0

    after = _count_open()
    print("[open_positions_after ]", after, flush=True)
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("[UNHANDLED]", repr(e), flush=True)
        traceback.print_exc()
        raise SystemExit(0)
