#!/usr/bin/env python3
import csv, os, sqlite3, time

CSV_PATH = os.getenv("WALLET_CSV", "state/imports/wallet_export.csv")
DB_PATH  = os.getenv("BRAIN_DB", "state/brain.sqlite")

def ensure_schema(con: sqlite3.Connection):
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")

    con.execute("""
    CREATE TABLE IF NOT EXISTS wallet_transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        block_time INTEGER,
        human_time TEXT,
        flow TEXT,
        token_address TEXT,
        symbol TEXT,
        amount_raw TEXT,
        decimals INTEGER,
        ui_amount REAL,
        action TEXT,
        from_addr TEXT,
        to_addr TEXT,
        tx_signature TEXT,
        value_usd REAL,
        src_file TEXT,
        imported_at INTEGER
    );
    """)

    con.execute("""
    CREATE INDEX IF NOT EXISTS idx_wallet_transfers_token_time
    ON wallet_transfers(token_address, block_time);
    """)

    con.execute("""
    CREATE INDEX IF NOT EXISTS idx_wallet_transfers_sig
    ON wallet_transfers(tx_signature);
    """)

    con.execute("""
    CREATE TABLE IF NOT EXISTS token_stats (
        token_address TEXT PRIMARY KEY,
        symbol TEXT,
        last_seen INTEGER,
        n_events INTEGER,
        n_in INTEGER,
        n_out INTEGER,
        ui_in REAL,
        ui_out REAL,
        ui_net REAL,
        usd_in REAL,
        usd_out REAL,
        usd_net REAL,
        computed_at INTEGER
    );
    """)

def fnum(x, default=0.0):
    try:
        if x is None: return default
        s = str(x).strip()
        if s == "": return default
        return float(s)
    except Exception:
        return default

def fint(x, default=0):
    try:
        if x is None: return default
        s = str(x).strip()
        if s == "": return default
        return int(float(s))
    except Exception:
        return default

def main():
    if not os.path.exists(CSV_PATH):
        raise SystemExit(f"CSV not found: {CSV_PATH}")

    con = sqlite3.connect(DB_PATH)
    ensure_schema(con)

    imported_at = int(time.time())
    src_file = os.path.basename(CSV_PATH)

    # Detect delimiter (some exports use ; )
    with open(CSV_PATH, "r", encoding="utf-8", errors="replace", newline="") as f:
        sample = f.read(4096)
    delim = ";" if sample.count(";") > sample.count(",") else ","

    n = 0
    with open(CSV_PATH, "r", encoding="utf-8", errors="replace", newline="") as f:
        r = csv.DictReader(f, delimiter=delim)
        cols = set(r.fieldnames or [])
        # expected: Block Time, Human Time, Flow, Token Address, Symbol, Amount, Decimals, Action, From, To, Signature, Value
        for row in r:
            bt = fint(row.get("Block Time"))
            human = (row.get("Human Time") or "").strip()
            flow = (row.get("Flow") or "").strip().lower()  # in/out
            token = (row.get("Token Address") or "").strip()
            sym = (row.get("Symbol") or "").strip()
            amount_raw = (row.get("Amount") or "").strip()
            dec = fint(row.get("Decimals"))
            ui = fnum(amount_raw) / (10 ** dec) if dec >= 0 and amount_raw != "" else fnum(row.get("UI Amount"), 0.0)
            action = (row.get("Action") or "").strip()
            fa = (row.get("From") or "").strip()
            ta = (row.get("To") or "").strip()
            sig = (row.get("Signature") or row.get("Tx Signature") or "").strip()
            val = fnum(row.get("Value"))

            con.execute("""
            INSERT INTO wallet_transfers(
                block_time,human_time,flow,token_address,symbol,amount_raw,decimals,ui_amount,
                action,from_addr,to_addr,tx_signature,value_usd,src_file,imported_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (bt, human, flow, token, sym, amount_raw, dec, ui, action, fa, ta, sig, val, src_file, imported_at))
            n += 1

            if n % 2000 == 0:
                con.commit()

    con.commit()

    # compute stats
    con.execute("DELETE FROM token_stats;")
    con.execute("""
    INSERT INTO token_stats(token_address, symbol, last_seen, n_events, n_in, n_out, ui_in, ui_out, ui_net, usd_in, usd_out, usd_net, computed_at)
    SELECT
      token_address,
      MAX(symbol) as symbol,
      MAX(block_time) as last_seen,
      COUNT(*) as n_events,
      SUM(CASE WHEN flow='in'  THEN 1 ELSE 0 END) as n_in,
      SUM(CASE WHEN flow='out' THEN 1 ELSE 0 END) as n_out,
      SUM(CASE WHEN flow='in'  THEN ui_amount ELSE 0 END) as ui_in,
      SUM(CASE WHEN flow='out' THEN ui_amount ELSE 0 END) as ui_out,
      SUM(CASE WHEN flow='in'  THEN ui_amount ELSE -ui_amount END) as ui_net,
      SUM(CASE WHEN flow='in'  THEN value_usd ELSE 0 END) as usd_in,
      SUM(CASE WHEN flow='out' THEN value_usd ELSE 0 END) as usd_out,
      SUM(CASE WHEN flow='in'  THEN value_usd ELSE -value_usd END) as usd_net,
      ?
    FROM wallet_transfers
    WHERE token_address IS NOT NULL AND token_address != ''
    GROUP BY token_address;
    """, (int(time.time()),))
    con.commit()

    # quick report
    cur = con.execute("SELECT COUNT(*) FROM wallet_transfers;")
    total = cur.fetchone()[0]
    cur = con.execute("SELECT COUNT(*) FROM token_stats;")
    ntok = cur.fetchone()[0]

    print(f"✅ imported rows={n} (db_total={total}) tokens={ntok} db={DB_PATH}")
    print("Top tokens by events:")
    for row in con.execute("SELECT token_address,symbol,n_events,ui_net,usd_net,last_seen FROM token_stats ORDER BY n_events DESC LIMIT 10;"):
        print("  ", row)

    con.close()

if __name__ == "__main__":
    main()
