import sqlite3
import time
from typing import Any, Dict, List


class PositionsDBAdapter:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _con(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    # ---------- schema helpers ----------
    def _cols(self):
        con = self._con()
        try:
            cur = con.cursor()
            return [r[1] for r in cur.execute("PRAGMA table_info(positions)").fetchall()]
        finally:
            con.close()

    def _entry_col(self, cols):
        return "entry_price_usd" if "entry_price_usd" in cols else (
            "entry_price" if "entry_price" in cols else None
        )

    def _close_col(self, cols):
        return "close_price_usd" if "close_price_usd" in cols else (
            "close_price" if "close_price" in cols else None
        )

    def _high_col(self, cols):
        return "high_water" if "high_water" in cols else (
            "max_price" if "max_price" in cols else None
        )

    def _trail_col(self, cols):
        return "trailing_stop" if "trailing_stop" in cols else (
            "stop_price" if "stop_price" in cols else None
        )

    # ---------- public API ----------
    def get_open_positions(self) -> List[Dict[str, Any]]:
        con = self._con()
        con.row_factory = sqlite3.Row
        try:
            cur = con.cursor()
            rows = cur.execute(
                "SELECT * FROM positions WHERE LOWER(status)='open'"
            ).fetchall()
            out = [dict(r) for r in rows]
        finally:
            con.close()

        cols = self._cols()

        for r in out:
            r.setdefault("entry_price_usd", r.get(self._entry_col(cols)))
            r.setdefault("close_price_usd", r.get(self._close_col(cols)))
            r.setdefault("high_water", r.get(self._high_col(cols)))
            r.setdefault("trailing_stop", r.get(self._trail_col(cols)))
            r.setdefault("wallet", "")

        return out

    def update_position(self, mint: str, **fields) -> None:
        if not fields:
            return

        cols = self._cols()
        mapped = {}

        for k, v in fields.items():
            if k in ("entry_price_usd", "entry_price"):
                c = self._entry_col(cols)
            elif k in ("close_price_usd", "close_price"):
                c = self._close_col(cols)
            elif k == "high_water":
                c = self._high_col(cols)
            elif k == "trailing_stop":
                c = self._trail_col(cols)
            else:
                c = k if k in cols else None

            if c:
                mapped[c] = v

        if not mapped:
            return

        sets = ", ".join(f"{k}=?" for k in mapped)
        vals = list(mapped.values()) + [mint]

        con = self._con()
        try:
            cur = con.cursor()
            cur.execute(f"UPDATE positions SET {sets} WHERE mint=?", vals)
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
    def close_position(self, mint: str, *args, **kwargs) -> None:
        """Close a position in a schema-compatible way.

        Supported call styles found in the repo history:
          - close_position(mint, reason="...")
          - close_position(mint, close_reason="...")
          - close_position(mint, now, "reason", close_price)
        We normalize and then update:
          close_ts, close_reason, close_price (optional), status='closed' (if column exists)
        Only affects rows that are still open ((close_ts IS NULL OR close_ts=0)).
        """
        import time, sqlite3

        # --- normalize inputs ---
        now = None
        close_reason = None
        close_price = None

        if len(args) >= 1 and isinstance(args[0], (int, float)):
            now = int(args[0])
        if len(args) >= 2 and isinstance(args[1], str):
            close_reason = args[1]
        if len(args) >= 3 and isinstance(args[2], (int, float)):
            close_price = float(args[2])

        close_reason = kwargs.get("close_reason", kwargs.get("reason", close_reason))
        if "close_price" in kwargs:
            try:
                close_price = float(kwargs["close_price"])
            except Exception:
                pass
        if now is None:
            now = int(time.time())
        if close_reason is None:
            close_reason = "closed"

        con = sqlite3.connect(self.db_path)
        try:
            con.row_factory = sqlite3.Row
            cur = con.cursor()

            cols = [r["name"] for r in cur.execute("PRAGMA table_info(positions)")]
            has_status = "status" in cols
            has_close_price = "close_price" in cols

            sets = ["close_ts = ?", "close_reason = ?"]
            params = [int(now), str(close_reason)]

            if has_close_price:
                # allow NULL if not provided
                sets.append("close_price = ?")
                params.append(None if close_price is None else float(close_price))

            if has_status:
                sets.append("status='closed'")

            params.append(str(mint))

            q = f"UPDATE positions SET {', '.join(sets)} WHERE mint = ? AND (close_ts IS NULL OR close_ts=0)"
            cur.execute(q, params)
            con.commit()
        finally:
            con.close()

