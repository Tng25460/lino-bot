import os, sqlite3, time
from pathlib import Path

DB = Path(os.getenv("BRAIN_DB", "state/brain.sqlite"))

def main():
    DB.parent.mkdir(parents=True, exist_ok=True)

    if DB.exists():
        bkp = DB.with_suffix(".sqlite.bak_" + time.strftime("%Y%m%d_%H%M%S"))
        DB.replace(bkp)
        print(f"✅ backup old brain db -> {bkp}")

    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA temp_store=MEMORY;")

    con.executescript("""
    CREATE TABLE IF NOT EXISTS brain_runs (
      run_id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts_start INTEGER NOT NULL,
      ts_end   INTEGER,
      mode     TEXT,
      notes    TEXT
    );

    -- wallet events with clean INTEGER columns (slot/fee/lamports)
    CREATE TABLE IF NOT EXISTS wallet_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL,
      slot INTEGER,
      signature TEXT,
      owner TEXT,
      err TEXT,
      fee_lamports INTEGER,
      raw_json TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_wallet_events_ts ON wallet_events(ts);
    CREATE INDEX IF NOT EXISTS idx_wallet_events_sig ON wallet_events(signature);

    -- token observations from sources (dexscreener/jupiter/wallet)
    CREATE TABLE IF NOT EXISTS token_observations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL,
      mint TEXT NOT NULL,
      source TEXT,
      price REAL,
      liq_usd REAL,
      vol_5m REAL,
      vol_1h REAL,
      txns_5m INTEGER,
      txns_1h INTEGER,
      holders INTEGER,
      top10_pct REAL,
      flags TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_obs_mint_ts ON token_observations(mint, ts);

    -- final scores exported
    CREATE TABLE IF NOT EXISTS token_scores (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL,
      mint TEXT NOT NULL,
      profile TEXT,
      score REAL NOT NULL,
      reason TEXT,
      payload_json TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_scores_ts ON token_scores(ts);
    CREATE INDEX IF NOT EXISTS idx_scores_mint ON token_scores(mint);
    """)

    con.commit()
    con.close()
    print(f"✅ initialized brain db v4 -> {DB}")

if __name__ == "__main__":
    main()
