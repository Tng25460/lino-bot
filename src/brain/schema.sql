PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS brain_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  note TEXT
);

-- Résumé par mint dérivé de trades.sqlite (et/ou wallet csv)
CREATE TABLE IF NOT EXISTS mint_stats (
  mint TEXT PRIMARY KEY,
  last_update_ts INTEGER NOT NULL,

  trades_total INTEGER DEFAULT 0,
  trades_closed INTEGER DEFAULT 0,

  wins INTEGER DEFAULT 0,
  losses INTEGER DEFAULT 0,

  tp1_hits INTEGER DEFAULT 0,
  tp2_hits INTEGER DEFAULT 0,
  sl_hits INTEGER DEFAULT 0,
  time_stops INTEGER DEFAULT 0,

  avg_pnl REAL,
  median_pnl REAL,
  worst_pnl REAL,
  best_pnl REAL,

  avg_hold_sec REAL,
  median_hold_sec REAL,

  last_close_reason TEXT
);

-- Score final (ce que le bot doit consommer)
CREATE TABLE IF NOT EXISTS mint_scores (
  mint TEXT PRIMARY KEY,
  scored_at_ts INTEGER NOT NULL,
  score REAL NOT NULL,

  -- composantes utiles debug
  score_market REAL,
  score_flow REAL,
  score_history REAL,

  reason TEXT
);

-- Wallet events optionnel (pour plus tard / debug)
CREATE TABLE IF NOT EXISTS wallet_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER,
  signature TEXT,
  action TEXT,
  mint TEXT,
  decimals INTEGER,
  amount_raw REAL,
  flow TEXT,
  from_addr TEXT,
  to_addr TEXT,
  value_usd REAL,
  source TEXT
);

CREATE INDEX IF NOT EXISTS idx_wallet_events_token_ts ON wallet_events(mint, ts);
