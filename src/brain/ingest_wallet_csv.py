import os, csv, sqlite3, time

BRAIN_DB=os.getenv("BRAIN_DB","state/brain.sqlite")
CSV_PATH=os.getenv("WALLET_CSV","")

def main():
    if not CSV_PATH or not os.path.exists(CSV_PATH):
        raise SystemExit(f"missing WALLET_CSV or file not found: {CSV_PATH}")

    con=sqlite3.connect(BRAIN_DB)
    cur=con.cursor()
    n=0
    with open(CSV_PATH,"r",encoding="utf-8",newline="") as f:
        reader=csv.DictReader(f)
        for row in reader:
            # best effort mapping from your export columns
            ts=row.get("Block Time") or row.get("block_time") or ""
            try:
                ts=int(float(ts)) if ts else None
            except Exception:
                ts=None
            cur.execute("""
            INSERT INTO wallet_events(ts,signature,action,token_address,decimals,amount_raw,flow,from_addr,to_addr,value_usd,source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                ts,
                row.get("Signature") or row.get("signature"),
                row.get("Action") or row.get("action"),
                row.get("Token Address") or row.get("token_address"),
                int(row.get("Decimals") or 0),
                float(row.get("Amount") or 0.0),
                row.get("Flow") or row.get("flow"),
                row.get("From") or row.get("from"),
                row.get("To") or row.get("to"),
                float(row.get("Value") or 0.0) if (row.get("Value") not in (None,"")) else None,
                "csv"
            ))
            n += 1
            if n % 1000 == 0:
                con.commit()
    con.commit()
    con.close()
    print(f"✅ ingested {n} wallet rows into {BRAIN_DB}")

if __name__=="__main__":
    main()
