-- LINO unified schema (backward compatible)

CREATE TABLE IF NOT EXISTS trades(
  mint TEXT PRIMARY KEY,
  first_seen_ts INTEGER NOT NULL,
  last_ts INTEGER NOT NULL,
  status TEXT NOT NULL,
  last_error TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS positions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mint TEXT NOT NULL,
  status TEXT NOT NULL,
  entry_price REAL NOT NULL,
  peak_price REAL,
  size_sol REAL NOT NULL,
  tp_done INTEGER NOT NULL DEFAULT 0,
  entry_ts INTEGER NOT NULL,
  tx_sig TEXT NOT NULL DEFAULT '',
  meta_json TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  mint TEXT NOT NULL,
  status TEXT NOT NULL,
  err TEXT NOT NULL DEFAULT '',
  data_json TEXT NOT NULL DEFAULT '{}',
  data TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_mint ON positions(mint);
