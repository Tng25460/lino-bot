import os, json, time, sqlite3, urllib.request, urllib.error

RPC=os.environ.get("RPC_URL","https://api.mainnet-beta.solana.com")
DB=os.environ.get("DB_PATH","state/trades.sqlite")
WALLET=os.environ["WALLET"]

SLEEP=float(os.environ.get("SYNC_SLEEP_S","0.35"))
MAX_RETRY=int(os.environ.get("SYNC_MAX_RETRY","12"))

def rpc_call(method, params):
    payload={"jsonrpc":"2.0","id":1,"method":method,"params":params}
    data=json.dumps(payload).encode()
    for attempt in range(MAX_RETRY):
        try:
            req=urllib.request.Request(RPC, data=data, headers={"Content-Type":"application/json"})
            raw=urllib.request.urlopen(req, timeout=25).read().decode()
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                backoff=min(8.0, 0.5*(2**attempt))
                print(f"[429] {method} backoff={backoff:.2f}s attempt={attempt+1}/{MAX_RETRY}")
                time.sleep(backoff)
                continue
            raise

def onchain_ui(mint: str):
    res=rpc_call("getTokenAccountsByOwner",[WALLET,{"mint":mint},{"encoding":"jsonParsed","commitment":"processed"}])
    vals=(res.get("result") or {}).get("value") or []
    ui=0.0; dec=None
    for v in vals:
        info=v["account"]["data"]["parsed"]["info"]
        ta=info["tokenAmount"]
        ui += float(ta.get("uiAmountString") or "0")
        dec = int(ta["decimals"])
    return ui, dec, len(vals)

def main():
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row
    cur=con.cursor()

    cur.execute("PRAGMA table_info(positions)")
    cols=[r[1] for r in cur.fetchall()]
    if "status" not in cols:
        raise SystemExit("positions.status missing")
    if "qty_token" not in cols:
        raise SystemExit("positions.qty_token missing")

    cur.execute("SELECT mint, qty_token, status, close_ts FROM positions WHERE status='OPEN' ORDER BY entry_ts DESC")
    rows=cur.fetchall()
    print("open_positions =", len(rows))

    now=int(time.time())
    closed=0; updated=0

    for r in rows:
        mint=r["mint"]
        ui, dec, n = onchain_ui(mint)
        print(f"mint={mint} onchain_ui={ui} dec={dec} accounts={n}")

        # sync qty_token always
        cur.execute("UPDATE positions SET qty_token=? WHERE mint=? AND status='OPEN'", (ui, mint))
        updated += cur.rowcount

        if ui <= 0.0:
            cur.execute(
                "UPDATE positions SET status='CLOSED', close_ts=?, close_reason=? WHERE mint=? AND status='OPEN'",
                (now, "onchain_zero", mint)
            )
            closed += cur.rowcount

        con.commit()
        time.sleep(SLEEP)

    print("updated_qty_token =", updated)
    print("closed_onchain_zero =", closed)

if __name__ == "__main__":
    main()
