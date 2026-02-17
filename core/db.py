from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence

DEFAULT_DB_PATH = os.getenv("TRADES_DB_PATH", "state/trades.sqlite")


def now_ts() -> int:
    return int(time.time())


def _mkdir_parent(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _connect(path: str) -> sqlite3.Connection:
    _mkdir_parent(path)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def _cols(con: sqlite3.Connection, table: str) -> List[str]:
    try:
        return [r["name"] for r in con.execute(f"PRAGMA table_info({table})")]
    except Exception:
        return []


def _add_col(con: sqlite3.Connection, table: str, col: str, decl: str) -> None:
    cols = _cols(con, table)
    if col in cols:
        return
    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init_db(path: str = DEFAULT_DB_PATH) -> None:
    con = _connect(path)
    try:
        # Base tables (create if missing)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
              k TEXT PRIMARY KEY,
              v TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS positions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              mint TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'OPEN',
              entry_price REAL,
              peak_price REAL,
              size_sol REAL,
              tp_done INTEGER NOT NULL DEFAULT 0,
              entry_ts INTEGER,
              tx_sig TEXT NOT NULL DEFAULT '',
              meta_json TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts INTEGER NOT NULL,
              mint TEXT NOT NULL,
              status TEXT NOT NULL,
              err TEXT NOT NULL DEFAULT '',
              data_json TEXT NOT NULL DEFAULT '',
              data TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS trades (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              mint TEXT NOT NULL,
              first_seen_ts INTEGER NOT NULL,
              last_ts INTEGER NOT NULL,
              status TEXT NOT NULL,
              last_error TEXT NOT NULL DEFAULT '',
              payload_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )

        # Migrations / compatibility:
        # - positions.wallet (your new code expects it)
        _add_col(con, "positions", "wallet", "TEXT NOT NULL DEFAULT ''")
        _add_col(con, "positions", "symbol", "TEXT")
        _add_col(con, "positions", "qty_token", "REAL NOT NULL DEFAULT 0")
        _add_col(con, "positions", "entry_price_usd", "REAL")
        _add_col(con, "positions", "entry_cost_usd", "REAL")
        _add_col(con, "positions", "close_price_usd", "REAL")
        _add_col(con, "positions", "close_ts", "INTEGER")
        _add_col(con, "positions", "close_reason", "TEXT")

        # - trades.wallet (optional but useful)
        _add_col(con, "trades", "wallet", "TEXT NOT NULL DEFAULT ''")
        _add_col(con, "trades", "symbol", "TEXT")
        _add_col(con, "trades", "side", "TEXT NOT NULL DEFAULT 'BUY'")
        _add_col(con, "trades", "qty_token", "REAL NOT NULL DEFAULT 0")
        _add_col(con, "trades", "price_usd", "REAL")
        _add_col(con, "trades", "notional_usd", "REAL")
        _add_col(con, "trades", "tx_sig", "TEXT NOT NULL DEFAULT ''")
        _add_col(con, "trades", "route", "TEXT NOT NULL DEFAULT ''")
        _add_col(con, "trades", "err", "TEXT NOT NULL DEFAULT ''")
        _add_col(con, "trades", "created_ts", "INTEGER")
        _add_col(con, "trades", "updated_ts", "INTEGER")

        con.commit()
    finally:
        con.close()


@dataclass
class DB:
    path: str = DEFAULT_DB_PATH

    def _con(self) -> sqlite3.Connection:
        return _connect(self.path)

    def exec(self, sql: str, params: Sequence[Any] = ()) -> None:
        con = self._con()
        try:
            con.execute(sql, params)
            con.commit()
        finally:
            con.close()

    def one(self, sql: str, params: Sequence[Any] = ()) -> Optional[dict]:
        con = self._con()
        try:
            cur = con.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            con.close()

    def all(self, sql: str, params: Sequence[Any] = ()) -> List[dict]:
        con = self._con()
        try:
            cur = con.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        finally:
            con.close()


def upsert_open_position(
    db: DB,
    *,
    wallet: str,
    mint: str,
    symbol: Optional[str],
    qty_token: float,
    entry_price_usd: Optional[float],
    entry_cost_usd: Optional[float],
    ts: Optional[int] = None,
    tx_sig: str = "",
    meta_json: str = "",
) -> None:
    ts = now_ts() if ts is None else int(ts)
    # ensure exists
    row = db.one("SELECT id FROM positions WHERE wallet=? AND mint=? AND LOWER(status)='open' LIMIT 1", (wallet, mint))
    if row:
        db.exec(
            """
            UPDATE positions
            SET qty_token=?, symbol=COALESCE(?,symbol),
                entry_price_usd=COALESCE(?,entry_price_usd),
                entry_cost_usd=COALESCE(?,entry_cost_usd),
                entry_ts=COALESCE(entry_ts, ?),
                tx_sig=CASE WHEN tx_sig='' THEN ? ELSE tx_sig END,
                meta_json=CASE WHEN meta_json='' THEN ? ELSE meta_json END
            WHERE id=?
            """,
            (float(qty_token), symbol, entry_price_usd, entry_cost_usd, ts, tx_sig or "", meta_json or "", row["id"]),
        )
    else:
        db.exec(
            """
            INSERT INTO positions(wallet,mint,symbol,status,qty_token,entry_price_usd,entry_cost_usd,entry_ts,tx_sig,meta_json)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (wallet, mint, symbol, "OPEN", float(qty_token), entry_price_usd, entry_cost_usd, ts, tx_sig or "", meta_json or ""),
        )


def close_position(
    db: DB,
    *,
    wallet: str,
    mint: str,
    close_price_usd: Optional[float],
    reason: str,
    ts: Optional[int] = None,
) -> None:
    ts = now_ts() if ts is None else int(ts)
    db.exec(
        """
        UPDATE positions
        SET status='CLOSED', close_price_usd=?, close_ts=?, close_reason=?
        WHERE wallet=? AND mint=? AND LOWER(status)='open'
        """,
        (close_price_usd, ts, reason, wallet, mint),
    )


def update_position_marks(conn, mint: str, *, high_water=None, trailing_stop=None, tp1_done=None, tp2_done=None):
    """
    Compat helper expected by src/sell_engine.py
    Updates trailing/high + TP marks for a position row.
    """
    fields = []
    params = {}

    if high_water is not None:
        fields.append("high_water = :high_water")
        params["high_water"] = float(high_water)

    if trailing_stop is not None:
        fields.append("trailing_stop = :trailing_stop")
        params["trailing_stop"] = float(trailing_stop)

    if tp1_done is not None:
        fields.append("tp1_done = :tp1_done")
        params["tp1_done"] = int(tp1_done)

    if tp2_done is not None:
        fields.append("tp2_done = :tp2_done")
        params["tp2_done"] = int(tp2_done)

    if not fields:
        return

    params["mint"] = mint
    sql = "UPDATE positions SET " + ", ".join(fields) + " WHERE mint = :mint"
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()


# --- compat: expected by src/sell_engine.py ---
def mark_tp_done(conn, mint: str, tp_idx: int = 1, done: int = 1):
    """Mark TP as done in positions table (tp1_done/tp2_done)."""
    col = "tp1_done" if int(tp_idx) == 1 else "tp2_done"
    cur = conn.cursor()
    cur.execute(f"UPDATE positions SET {col} = ? WHERE mint = ?", (int(done), mint))
    conn.commit()
