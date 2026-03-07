import sqlite3
import time
from typing import Any, Dict, List, Optional


class PositionsDBAdapter:
    """
    Adapter minimal SQLite pour SellEngine.

    Méthodes attendues par core/sell_engine.py :
      - get_open_positions()
      - update_position(mint, **fields)
      - mark_tp1(mint)
      - mark_tp2(mint)
      - close_position(mint, reason)
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def get_open_positions(self) -> List[Dict[str, Any]]:
        con = self._con()
        try:
            cur = con.cursor()
            # OPEN = case-insensitive + compat NULL/''
            cur.execute("""
                SELECT *
                FROM positions
                WHERE (status IS NULL OR status = '' OR lower(status) = 'open')
                ORDER BY entry_ts ASC
            """)
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def update_position(self, mint: str, **fields) -> None:
        if not fields:
            return
        cols = []
        vals = []
        for k, v in fields.items():
            cols.append(f"{k}=?")
            vals.append(v)
        vals.append(mint)

        con = self._con()
        try:
            cur = con.cursor()
            cur.execute(f"UPDATE positions SET {', '.join(cols)} WHERE mint=?", vals)
            con.commit()
        finally:
            con.close()

    def mark_tp1(self, mint: str) -> None:
        con = self._con()
        try:
            cur = con.cursor()
            cur.execute("UPDATE positions SET tp1_done=1 WHERE mint=?", (mint,))
            con.commit()
        finally:
            con.close()

    def mark_tp2(self, mint: str) -> None:
        con = self._con()
        try:
            cur = con.cursor()
            cur.execute("UPDATE positions SET tp2_done=1 WHERE mint=?", (mint,))
            con.commit()
        finally:
            con.close()

    def close_position(self, mint: str, reason: str = "closed") -> None:
        now = time.time()
        con = self._con()
        try:
            cur = con.cursor()
            cur.execute("""
                UPDATE positions
                SET status='CLOSED',
                    close_ts=?,
                    close_reason=?
                WHERE mint=?
            """, (now, reason, mint))
            con.commit()
        finally:
            con.close()
