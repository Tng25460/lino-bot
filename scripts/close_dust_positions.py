import os, json, time, sqlite3, urllib.request, urllib.error

RPC=os.environ["RPC_URL"]
DB=os.environ["DB_PATH"]
WALLET=os.environ["WALLET_PUBKEY"]
DUST_MAX=int(os.environ.get("DUST_MAX_BASE_UNITS","1"))

def rpc_call(method, params, max_retry=12):
    payload={"jsonrpc":"2.0","id":1,"method":method,"params":params}
    data=json.dumps(payload).encode()
    for attempt in range(max_retry):
        try:
            req=urllib.request.Request(RPC, data=data, headers={"Content-Type":"application/json"})
            raw=urllib.request.urlopen(req, timeout=25).read().decode()
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                backoff=min(8.0, 0.5*(2**attempt))
                print(f"[429] {method} backoff={backoff:.2f}s attempt={attempt+1}/{max_retry}")
                time.sleep(backoff)
                continue
            raise

def onchain_amount_base(mint: str):
    res=rpc_call("getTokenAccountsByOwner", [WALLET, {"mint": mint}, {"encoding":"jsonParsed","commitment":"processed"}])
    vals=(res.get("result") or {}).get("value") or []
    total_base=0
    dec=None
    for v in vals:
        info=v["account"]["data"]["parsed"]["info"]
        amt=info["tokenAmount"]
        dec = int(amt["decimals"])
        total_base += int(amt["amount"])
    return total_base, dec, len(vals)

def main():
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row
    cur=con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables=[r[0] for r in cur.fetchall()]
    if "positions" not in tables:
        raise SystemExit("positions table not found")

    cur.execute("PRAGMA table_info(positions)")
    cols=[r[1] for r in cur.fetchall()]
    if "status" not in cols:
        raise SystemExit("positions.status missing")

    # OPEN rows: status='OPEN' and close_ts is null (si col existe)
    where="status='OPEN'"
    if "close_ts" in cols:
        where += " AND close_ts IS NULL"

    cur.execute(f"SELECT mint, qty_token, status, close_ts, close_reason FROM positions WHERE {where}")
    rows=cur.fetchall()
    print("open_positions =", len(rows))

    to_close=[]
    for r in rows:
        mint=r["mint"]
        base, dec, n = onchain_amount_base(mint)
        if base <= DUST_MAX:
            to_close.append((mint, base, dec, n))

    print("dust_to_close =", len(to_close), f"(<= {DUST_MAX} base units)")
    now=int(time.time())

    for mint, base, dec, n in to_close:
        print(f"- CLOSE mint={mint} onchain_base={base} dec={dec} accounts={n} reason=dust_untradeable")
        # on set qty_token=0 (si col existe) et on close
        sets=[]
        params=[]
        sets.append("status=?"); params.append("CLOSED")
        if "close_ts" in cols: sets.append("close_ts=?"); params.append(now)
        if "close_reason" in cols: sets.append("close_reason=?"); params.append("dust_untradeable")
        if "qty_token" in cols: sets.append("qty_token=?"); params.append(0.0)
        q=f"UPDATE positions SET {', '.join(sets)} WHERE mint=? AND status='OPEN'"
        params.append(mint)
        cur.execute(q, params)

    con.commit()
    con.close()
    print("done.")

if __name__ == "__main__":
    main()
