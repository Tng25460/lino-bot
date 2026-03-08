"""
PHASE3_P3.1: Module DB write pour BUY trades.

Extrait de src/trader_exec.py sans aucune modification de logique.
Fonctions:
  - _db_cols(cur, table)      : colonnes d'une table SQLite
  - _db_insert(cur, table, data) : insert schema-safe
  - _db_record_buy_schema_safe(...) : enregistrement BUY (trades + positions)

Utilisé par: src/trader_exec.py (BUY), potentiellement core/sell_engine.py (SELL)
"""
from __future__ import annotations


def _db_cols(cur, table: str):
    return [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]


def _db_insert(cur, table: str, data: dict):
    cols = _db_cols(cur, table)
    if not cols:
        return False
    use = {k: v for k, v in data.items() if k in cols}
    if not use:
        return False
    keys = list(use.keys())
    q = f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join(['?'] * len(keys))})"
    cur.execute(q, [use[k] for k in keys])
    return True


def _db_record_buy_schema_safe(
    db_path: str,
    mint: str,
    txsig: str,
    symbol: str = "",
    qty_token: float = 0.0,
    price: float = 0.0,
    qty_sol: float = 0.0,
):
    """
    Schema-safe DB write for BUY:
      - trades(ts, side, mint, symbol, qty_token, price, txsig, qty)
      - positions(mint, symbol, qty_token, entry_price, entry_ts, max_price, stop_price, status)
    Avoids pnl_usd mismatch completely.
    """
    import sqlite3, time

    if not db_path:
        db_path = "state/trades.sqlite"

    con = sqlite3.connect(db_path, timeout=30)
    cur = con.cursor()

    # if already open position for this mint, do not duplicate
    try:
        cur.execute(
            "SELECT COUNT(*) FROM positions WHERE mint=? AND (status LIKE 'OPEN%')",
            (mint,),
        )
        if cur.fetchone()[0] > 0:
            # still record trade
            _db_insert(
                cur,
                "trades",
                {
                    "ts": int(time.time()),
                    "side": "BUY",
                    "mint": mint,
                    "symbol": symbol,
                    "qty_token": float(qty_token or 0.0),
                    "price": float(price or 0.0),
                    "txsig": txsig,
                    "qty": float(qty_sol or 0.0),
                },
            )
            con.commit()
            con.close()
            return True
    except Exception:
        pass

    now = int(time.time())

    _db_insert(
        cur,
        "trades",
        {
            "ts": now,
            "side": "BUY",
            "mint": mint,
            "symbol": symbol,
            "qty_token": float(qty_token or 0.0),
            "price": float(price or 0.0),
            "txsig": txsig,
            "qty": float(qty_sol or 0.0),
        },
    )

    _db_insert(
        cur,
        "positions",
        {
            "mint": mint,
            "symbol": symbol,
            "qty_token": float(qty_token or 0.0),
            "entry_price": float(price or 0.0),
            "entry_ts": now,
            "max_price": float(price or 0.0),
            "stop_price": 0.0,
            "status": "OPEN",
            "tp1_done": 0,
            "tp2_done": 0,
        },
    )

    con.commit()
    con.close()
    return True
