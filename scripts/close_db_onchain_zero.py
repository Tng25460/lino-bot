import os, json, time, sqlite3, urllib.request, urllib.error

RPC=os.environ["RPC_URL"]
DB=os.environ["DB_PATH"]
WALLET=os.environ["WALLET_PUBKEY"]

SLEEP_BETWEEN=float(os.environ.get("RECONCILE_SLEEP_S","0.35"))
MAX_RETRY=int(os.environ.get("RECONCILE_MAX_RETRY","12"))

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
        except Exception as e:
            backoff=min(8.0, 0.5*(2**attempt))
            print(f"[ERR] {method} {type(e).__name__}: {e} backoff={backoff:.2f}s attempt={attempt+1}/{MAX_RETRY}")
            time.sleep(backoff)
    raise RuntimeError(f"RPC failed after {MAX_RETRY} attempts: {method}")

def onchain_ui_balance(mint: str) -> float:
    res=rpc_call("getTokenAccountsByOwner", [WALLET, {"mint": mint}, {"encoding":"jsonParsed","commitment":"processed"}])
    vals=(res.get("result") or {}).get("value") or []
    ui=0.0
    for v in vals:
        info=v["account"]["data"]["parsed"]["info"]
        amt=info["tokenAmount"]
        try:
            ui += float(amt.get("uiAmountString") or 0.0)
        except Exception:
            pass
    return ui

def pick_positions_table(con: sqlite3.Connection):
    cur=con.cursor()
    for t in ("positions","open_positions","position"):
        try:
            cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{t}'")
            if cur.fetchone():
                return t
        except Exception:
            pass
    raise RuntimeError("No positions-like table found (positions/open_positions/position)")

def column_exists(cur, table, col):
    cur.execute(f"PRAGMA table_info({table})")
    cols=[r[1] for r in cur.fetchall()]
    return col in cols, cols

def main():
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row
    cur=con.cursor()
    table=pick_positions_table(con)

    has_mint, cols = column_exists(cur, table, "mint")
    if not has_mint:
        raise RuntimeError(f"{table}: missing mint column. cols={cols}")

    # select open candidates
    where="WHERE 1=1"
    if any(c in cols for c in ("is_open","open","closed_at","status")):
        if "is_open" in cols:
            where += " AND is_open=1"
        elif "open" in cols:
            where += " AND open=1"
        elif "closed_at" in cols:
            where += " AND (closed_at IS NULL OR closed_at=0)"
        elif "status" in cols:
            where += " AND status='open'"

    cur.execute(f"SELECT rowid, * FROM {table} {where}")
    rows=cur.fetchall()
    print(f"table={table} open_candidates={len(rows)}")

    close_cols=set(cols)
    ts=int(time.time())

    to_close=[]
    for i,r in enumerate(rows,1):
        mint=r["mint"]
        ui=onchain_ui_balance(mint)
        if ui == 0.0:
            to_close.append((r["rowid"], mint))
        if i % 10 == 0:
            print(f"[PROGRESS] {i}/{len(rows)} zero={len(to_close)}")
        time.sleep(SLEEP_BETWEEN)

    print(f"to_close={len(to_close)}")
    if not to_close:
        return

    # build update statement based on available columns
    sets=[]
    params=[]
    if "qty_token" in close_cols:
        sets.append("qty_token=0")
    if "qty_ui" in close_cols:
        sets.append("qty_ui=0")
    if "amount_ui" in close_cols:
        sets.append("amount_ui=0")
    if "close_reason" in close_cols:
        sets.append("close_reason=?"); params.append("onchain_zero")
    if "reason" in close_cols:
        sets.append("reason=?"); params.append("onchain_zero")
    if "is_open" in close_cols:
        sets.append("is_open=0")
    if "open" in close_cols:
        sets.append("open=0")
    if "status" in close_cols:
        sets.append("status=?"); params.append("closed")
    if "closed_at" in close_cols:
        sets.append("closed_at=?"); params.append(ts)
    if "updated_at" in close_cols:
        sets.append("updated_at=?"); params.append(ts)

    if not sets:
        raise RuntimeError(f"{table}: no closable columns found. cols={cols}")

    set_sql=", ".join(sets)

    for rowid,mint in to_close:
        cur.execute(f"UPDATE {table} SET {set_sql} WHERE rowid=?", params+[rowid])
        print(f"[CLOSED] mint={mint} rowid={rowid}")

    con.commit()
    con.close()
    print("✅ DB updated")

if __name__ == "__main__":
    main()
