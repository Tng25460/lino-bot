from __future__ import annotations
import os, asyncio, sqlite3, time

DEFAULT_DB = os.getenv("DB_PATH", "state/trades.sqlite")

def _db_open_positions(db_path: str, wallet: str | None = None):
    con = sqlite3.connect(db_path, timeout=10)
    cur = con.cursor()
    if wallet:
        rows = cur.execute("""
            SELECT mint, symbol, qty_token, entry_ts
            FROM positions
            WHERE status='OPEN' AND wallet=?
            ORDER BY entry_ts DESC
        """, (wallet,)).fetchall()
    else:
        rows = cur.execute("""
            SELECT mint, symbol, qty_token, entry_ts
            FROM positions
            WHERE status='OPEN'
            ORDER BY entry_ts DESC
        """).fetchall()
    con.close()
    return rows

async def _tick(db_path: str, wallet: str | None) -> None:
    rows = _db_open_positions(db_path, wallet)
    print(f"💰 sell_engine: open_positions={len(rows)}")
    if not rows:
        print("💤 sell_engine: no open positions -> skip")
        return
    for mint, sym, qty_token, entry_ts in rows[:10]:
        age = int(time.time()) - int(entry_ts or 0)
        print(f"   - OPEN mint={mint} sym={sym} qty_token={qty_token} age_s={age}")
    print("⚠️ sell_engine: DB OK, mais swap SELL pas encore câblé ici (on le fait après)")

class SellEngine:
    def __init__(self, db_path: str = DEFAULT_DB, wallet: str | None = None):
        self.db_path = db_path
        self.wallet = wallet

    async def run_once(self, wallet: str | None = None):
        await _tick(self.db_path, wallet or self.wallet)

def sell_engine(db_path: str | None = None, wallet: str | None = None):
    db_path = db_path or DEFAULT_DB
    print("✅ sell_engine: using DB reader (patched)")
    print("   db_path=", db_path)
    eng = SellEngine(db_path=db_path, wallet=wallet)
    asyncio.run(eng.run_once())
