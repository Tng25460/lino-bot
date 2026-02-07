#!/usr/bin/env python3
import argparse, os, sqlite3, time


def _pnl_pct_from_prices(entry_usd, close_usd):
    # Returns float pnl_pct, or None if cannot compute safely.
    try:
        if entry_usd is None or close_usd is None:
            return None
        e=float(entry_usd)
        c=float(close_usd)
        if e <= 0:
            return None
        return ((c - e) / e) * 100.0
    except Exception:
        return None

def _tables(con):
    cur=con.cursor()
    cur.execute("select name from sqlite_master where type='table'")
    return {r[0] for r in cur.fetchall()}

def _cols(con, table):
    cur=con.cursor()
    cur.execute(f"pragma table_info({table})")
    return [r[1] for r in cur.fetchall()]

def _pick_table(con, candidates):
    t=_tables(con)
    for c in candidates:
        if c in t:
            return c
    return None

def _ensure_brain_schema(con):
    cur=con.cursor()
    cur.execute("""
    create table if not exists trade_facts (
        id integer primary key autoincrement,
        src_db text not null,
        src_table text not null,
        src_rowid integer not null,
        mint text,
        entry_price real,
        exit_price real,
        qty_token real,
        pnl_sol real,
        pnl_pct real,
        opened_ts integer,
        closed_ts integer,
        close_reason text,
        tp1_done integer,
        tp2_done integer,
        updated_ts integer not null,
        unique(src_db, src_table, src_rowid)
    )
    """)
    cur.execute("create index if not exists idx_trade_facts_mint on trade_facts(mint)")
    cur.execute("create index if not exists idx_trade_facts_closed on trade_facts(closed_ts)")
    con.commit()

def _get_first_existing(cols, names, default=None):
    s=set(cols)
    for n in names:
        if n in s:
            return n
    return default

def _as_float(x):
    try:
        if x is None: return None
        return float(x)
    except Exception:
        return None

def _as_int(x):
    try:
        if x is None: return None
        return int(float(x))
    except Exception:
        return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--trades-db", default="state/trades.sqlite")
    ap.add_argument("--brain-db", default="state/brain.sqlite")
    ap.add_argument("--dry-run", action="store_true")
    args=ap.parse_args()

    if not os.path.exists(args.trades_db):
        print(f"❌ trades db missing: {args.trades_db}")
        return 2

    tcon=sqlite3.connect(args.trades_db)
    tcon.row_factory=sqlite3.Row

    # try common tables
    table=_pick_table(tcon, ["positions", "open_positions", "trades", "positions_v2"])
    if not table:
        print("❌ could not find a known table in trades db")
        print("tables=", sorted(_tables(tcon)))
        return 2

    cols=_cols(tcon, table)

    # map columns flexibly
    col_mint=_get_first_existing(cols, ["mint", "output_mint", "token_mint"])
    col_entry=_get_first_existing(cols, ["entry_price", "buy_price", "avg_entry_price"])
    col_exit=_get_first_existing(cols, ["exit_price", "sell_price", "close_price", "avg_exit_price"])
    col_qty=_get_first_existing(cols, ["qty_token", "amount_token", "token_qty", "qty"])
    col_pnl_sol=_get_first_existing(cols, ["pnl_sol", "pnl", "realized_pnl_sol"])
    col_pnl_pct=_get_first_existing(cols, ["pnl_pct", "pnl_percent", "realized_pnl_pct", "pnl_ratio"])
    col_opened=_get_first_existing(cols, ["opened_ts", "open_ts", "ts_open", "created_ts", "created_at"])
    col_closed=_get_first_existing(cols, ["closed_ts", "close_ts", "ts_close", "closed_at", "updated_ts", "updated_at"])
    col_reason=_get_first_existing(cols, ["close_reason", "reason", "exit_reason"])
    col_tp1=_get_first_existing(cols, ["tp1_done", "tp1", "did_tp1"])
    col_tp2=_get_first_existing(cols, ["tp2_done", "tp2", "did_tp2"])

    # closed filter (best effort)
    closed_pred = None
    if "is_open" in cols:
        closed_pred = "coalesce(is_open,1)=0"
    elif "status" in cols:
        closed_pred = "lower(coalesce(status,'')) in ('closed','done','exited')"
    elif col_closed:
        closed_pred = f"{col_closed} is not null and {col_closed}!=0"
    else:
        # if no way to detect closed, sync everything but still idempotent
        closed_pred = "1=1"

    q=f"select rowid as _rowid_, * from {table} where {closed_pred}"
    cur=tcon.cursor()
    rows=cur.execute(q).fetchall()
    print(f"== sync source == db={args.trades_db} table={table} rows={len(rows)} closed_pred=({closed_pred})")

    bcon=sqlite3.connect(args.brain_db)
    bcon.row_factory=sqlite3.Row
    _ensure_brain_schema(bcon)

    upserts=0
    now=int(time.time())
    for r in rows:
        rowid=int(r["_rowid_"])
        mint = r[col_mint] if col_mint else None

        entry=_as_float(r[col_entry]) if col_entry else None
        exitp=_as_float(r[col_exit]) if col_exit else None
        qty=_as_float(r[col_qty]) if col_qty else None
        pnl_sol=_as_float(r[col_pnl_sol]) if col_pnl_sol else None

        # Prefer USD prices when available (GOLD schema)
        # Supports sqlite3.Row (mapping) and dict; falls back safely.
        entry_usd = None
        close_usd = None
        try:
            if hasattr(r, "keys") and ("entry_price_usd" in r.keys()) and ("close_price_usd" in r.keys()):
                entry_usd = _as_float(r["entry_price_usd"])
                close_usd = _as_float(r["close_price_usd"])
        except Exception:
            entry_usd = None
            close_usd = None
        if entry_usd is not None and close_usd is not None:
            entry, exitp = entry_usd, close_usd
        pnl_pct=_as_float(r[col_pnl_pct]) if col_pnl_pct else None
        opened=_as_int(r[col_opened]) if col_opened else None
        closed=_as_int(r[col_closed]) if col_closed else None
        reason = r[col_reason] if col_reason else None
        tp1=_as_int(r[col_tp1]) if col_tp1 else None
        tp2=_as_int(r[col_tp2]) if col_tp2 else None

        # simple derivations if missing
        if pnl_pct is None and entry is not None and exitp is not None and entry != 0:
            pnl_pct=(exitp-entry)/entry
        if pnl_sol is None:
            pnl_sol=None

        if args.dry_run:
            continue

        bcon.execute("""
        insert into trade_facts(
            src_db, src_table, src_rowid,
            mint, entry_price, exit_price, qty_token,
            pnl_sol, pnl_pct, opened_ts, closed_ts,
            close_reason, tp1_done, tp2_done,
            updated_ts
        ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        on conflict(src_db, src_table, src_rowid) do update set
            mint=excluded.mint,
            entry_price=excluded.entry_price,
            exit_price=excluded.exit_price,
            qty_token=excluded.qty_token,
            pnl_sol=excluded.pnl_sol,
            pnl_pct=excluded.pnl_pct,
            opened_ts=excluded.opened_ts,
            closed_ts=excluded.closed_ts,
            close_reason=excluded.close_reason,
            tp1_done=excluded.tp1_done,
            tp2_done=excluded.tp2_done,
            updated_ts=excluded.updated_ts
        """, (
            args.trades_db, table, rowid,
            mint, entry, exitp, qty,
            pnl_sol, pnl_pct, opened, closed,
            reason, tp1, tp2,
            now
        ))
        upserts += 1

    if not args.dry_run:
        bcon.commit()

    print(f"✅ brain sync done: upserts={upserts} brain_db={args.brain_db}")

    # show quick stats
    cur=bcon.cursor()
    cur.execute("select count(*) from trade_facts")
    total=cur.fetchone()[0]
    cur.execute("select count(*) from trade_facts where pnl_pct is not null")
    with_pnl=cur.fetchone()[0]
    cur.execute("select close_reason, count(*) c from trade_facts group by close_reason order by c desc limit 10")
    top=cur.fetchall()
    print(f"== brain stats == total={total} with_pnl_pct={with_pnl}")
    print("top close_reason:")
    for rr in top:
        print(" -", rr[0], rr[1])

    bcon.close()
    tcon.close()
    return 0

if __name__=="__main__":
    raise SystemExit(main())
