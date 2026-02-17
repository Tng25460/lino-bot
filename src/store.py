import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


@dataclass
class TradeEvent:
    ts: int
    mint: str
    status: str
    data: Dict[str, Any]
    err: str = ""


class TradeStore:
    """
    SQLite store: idempotence + historique.
    Status: SEEN -> READY -> BUILT -> SIGNED -> SIM_OK/SIM_FAIL -> SENT
    """
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
              mint TEXT PRIMARY KEY,
              first_seen_ts INTEGER NOT NULL,
              last_ts INTEGER NOT NULL,
              status TEXT NOT NULL,
              last_error TEXT NOT NULL DEFAULT '',
              payload_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts INTEGER NOT NULL,
              mint TEXT NOT NULL,
              status TEXT NOT NULL,
              err TEXT NOT NULL DEFAULT '',
              data_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_events_mint_ts ON events(mint, ts);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);")
        self._conn.commit()

    def upsert_trade(self, mint: str, status: str, payload: Optional[Dict[str, Any]] = None, err: str = "") -> None:
        now = int(time.time())
        payload = payload or {}
        pj = json.dumps(payload, ensure_ascii=False)

        cur = self._conn.cursor()
        cur.execute("SELECT mint FROM trades WHERE mint=? LIMIT 1", (mint,))
        row = cur.fetchone()

        if row is None:
            cur.execute(
                """
                INSERT INTO trades(mint, first_seen_ts, last_ts, status, last_error, payload_json)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (mint, now, now, status, err, pj),
            )
        else:
            cur.execute(
                """
                UPDATE trades
                SET last_ts=?, status=?, last_error=?, payload_json=?
                WHERE mint=?
                """,
                (now, status, err, pj, mint),
            )

        cur.execute(
            "INSERT INTO events(ts, mint, status, err, data_json) VALUES(?, ?, ?, ?, ?)",
            (now, mint, status, err, pj),
        )
        self._conn.commit()

    def seen_before(self, mint: str) -> bool:
        cur = self._conn.cursor()
        cur.execute("SELECT 1 FROM trades WHERE mint=? LIMIT 1", (mint,))
        return cur.fetchone() is not None

    def get_trade(self, mint: str) -> Optional[Tuple[str, str]]:
        cur = self._conn.cursor()
        cur.execute("SELECT status, payload_json FROM trades WHERE mint=?", (mint,))
        row = cur.fetchone()
        return row if row else None

    # Convenience
    def mark_seen(self, mint: str, payload: Dict[str, Any]) -> None:
        self.upsert_trade(mint, "SEEN", payload)

    def mark_ready(self, mint: str, payload: Dict[str, Any]) -> None:
        self.upsert_trade(mint, "READY", payload)

    def mark_built(self, mint: str, payload: Dict[str, Any]) -> None:
        self.upsert_trade(mint, "BUILT", payload)

    def mark_signed(self, mint: str, payload: Dict[str, Any]) -> None:
        self.upsert_trade(mint, "SIGNED", payload)

    def mark_sim_ok(self, mint: str, payload: Dict[str, Any]) -> None:
        self.upsert_trade(mint, "SIM_OK", payload)

    def mark_sim_fail(self, mint: str, payload: Dict[str, Any], err: str) -> None:
        self.upsert_trade(mint, "SIM_FAIL", payload, err=err)

    def mark_sent(self, mint: str, payload: Dict[str, Any]) -> None:
        self.upsert_trade(mint, "SENT", payload)


    def update_status(self, mint: str, status: str, ts: int, data: dict, err: str = "") -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO trades (mint, status, last_ts, last_error, data)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(mint) DO UPDATE SET
                status=excluded.status,
                last_ts=excluded.last_ts,
                last_error=excluded.last_error,
                data=excluded.data
            """,
            (mint, status, ts, err, json.dumps(data))
        )
        cur.execute(
            "INSERT INTO events (ts, mint, status, err) VALUES (?, ?, ?, ?)",
            (ts, mint, status, err)
        )
        self._conn.commit()

    def update_status(self, mint: str, status: str, ts: int, data: dict, err: str = ""):
        cur = self._conn.cursor()
        cur.execute("""
            INSERT INTO trades(mint,status,first_seen_ts,last_ts,last_error)
            VALUES(?,?,?,?,?)
            ON CONFLICT(mint) DO UPDATE SET
                status=excluded.status,
                first_seen_ts=COALESCE(trades.first_seen_ts, excluded.first_seen_ts),
                last_ts=excluded.last_ts,
                last_error=excluded.last_error
        """, (mint, status, ts, ts, err))

        cur.execute("""
            INSERT INTO events(ts,mint,status,err,data_json) VALUES(?,?,?,?,?)
        """, (ts, mint, status, err, json.dumps(data)))
        self._conn.commit()


# ===============================
# SELL ENGINE HELPERS
# ===============================

import json as _json
import sqlite3 as _sqlite3

def _row_to_dict(_cur, _row):
    return {desc[0]: _row[i] for i, desc in enumerate(_cur.description)}

def _connect(db_path: str):
    con = _sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con

def _ensure_positions_table(con):
    con.execute("""
    CREATE TABLE IF NOT EXISTS positions(
        mint TEXT PRIMARY KEY,
        entry_price REAL NOT NULL,
        entry_ts INTEGER NOT NULL,
        size_sol REAL NOT NULL,
        peak_price REAL,
        tp_done INTEGER DEFAULT 0,
        status TEXT DEFAULT 'OPEN',
        meta_json TEXT DEFAULT ''
    )
    """)
    con.commit()

def _ensure_events_cols(con):
    # events doit avoir data_json; si pas, on ignore (déjà géré chez toi)
    return

class _SellMixin:
    def get_open_positions(self):
        con = _connect(self.db_path)
        _ensure_positions_table(con)
        cur = con.cursor()
        cur.execute("SELECT mint,entry_price,entry_ts,size_sol,peak_price,tp_done,status,meta_json FROM positions WHERE LOWER(status)='open'")
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            # meta_json -> dict
            try:
                d["meta"] = _json.loads(d.get("meta_json") or "{}")
            except Exception:
                d["meta"] = {}
            out.append(d)
        con.close()
        return out

    def update_peak(self, mint: str, peak_price: float):
        con = _connect(self.db_path)
        _ensure_positions_table(con)
        con.execute("UPDATE positions SET peak_price=? WHERE mint=?", (float(peak_price), mint))
        con.commit()
        con.close()

    def mark_partial_tp(self, mint: str, tp_pct: float):
        # ici: on marque tp_done=1 (et on log l'intention). L'exécution SELL on l’ajoute ensuite.
        con = _connect(self.db_path)
        _ensure_positions_table(con)
        con.execute("UPDATE positions SET tp_done=1 WHERE mint=?", (mint,))
        con.commit()
        con.close()

    def mark_sell(self, mint: str, reason: str = ""):
        con = _connect(self.db_path)
        _ensure_positions_table(con)
        con.execute("UPDATE positions SET status='SELL_SIGNAL' WHERE mint=?", (mint,))
        con.commit()
        con.close()

# patch dynamique: si TradeStore existe, on lui injecte les méthodes
try:
    TradeStore  # noqa
    if not hasattr(TradeStore, "get_open_positions"):
        for _name in ("get_open_positions","update_peak","mark_partial_tp","mark_sell"):
            setattr(TradeStore, _name, getattr(_SellMixin, _name))
except Exception:
    pass


# ===============================
# POSITIONS: insert/update after BUY confirmed
# ===============================
import json as __json

class __PositionMixin:
    def upsert_position(self, mint: str, entry_price: float, size_sol: float, entry_ts: int, meta: dict | None = None):
        con = _connect(self.db_path)
        _ensure_positions_table(con)
        meta_json = __json.dumps(meta or {}, ensure_ascii=False)
        con.execute(
            """
            INSERT INTO positions(mint, entry_price, entry_ts, size_sol, peak_price, tp_done, status, meta_json)
            VALUES(?,?,?,?,?,0,'OPEN',?)
            ON CONFLICT(mint) DO UPDATE SET
              entry_price=excluded.entry_price,
              entry_ts=excluded.entry_ts,
              size_sol=excluded.size_sol,
              peak_price=COALESCE(positions.peak_price, excluded.peak_price), status='open' ,
              meta_json=excluded.meta_json
            """,
            (mint, float(entry_price), int(entry_ts), float(size_sol), float(entry_price), meta_json),
        )
        con.commit()
        con.close()

try:
    TradeStore  # noqa
    if not hasattr(TradeStore, "upsert_position"):
        setattr(TradeStore, "upsert_position", getattr(__PositionMixin, "upsert_position"))
except Exception:
    pass
