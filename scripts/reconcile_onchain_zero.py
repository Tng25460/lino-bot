import os, json, time, sqlite3, urllib.request

RPC=os.environ["RPC_URL"]
DB=os.environ["DB_PATH"]
WALLET=os.environ["WALLET_PUBKEY"]

def rpc_call(method, params):
    payload={"jsonrpc":"2.0","id":1,"method":method,"params":params}
    req=urllib.request.Request(RPC, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=25).read().decode())

def onchain_ui_balance(mint: str) -> float:
    res=rpc_call("getTokenAccountsByOwner", [WALLET, {"mint": mint}, {"encoding":"jsonParsed","commitment":"processed"}])
    vals=(res.get("result") or {}).get("value") or []
    ui=0.0
    for v in vals:
        info=v["account"]["data"]["parsed"]["info"]
        amt=info["tokenAmount"]
        s=amt.get("uiAmountString")
        if s is None:
            # fallback
            ui += float(amt.get("uiAmount") or 0.0)
        else:
            try: ui += float(s)
            except: pass
    return ui

def table_exists(con, name):
    r=con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return bool(r)

def pick_positions_table(con):
    for t in ("positions","open_positions","position"):
        if table_exists(con, t): return t
    raise SystemExit("FATAL: no positions table found (tried positions/open_positions/position)")

def cols(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]

def detect_open_where(columns):
    # returns (where_sql, params)
    if "is_open" in columns:
        return ("is_open=1", ())
    if "status" in columns:
        return ("status IN ('open','OPEN','active','ACTIVE')", ())
    if "closed_at" in columns:
        return ("(closed_at IS NULL OR closed_at=0 OR closed_at='')", ())
    # fallback: assume all rows are candidates
    return ("1=1", ())

def close_update_sql(table, columns):
    sets=[]
    params=[]
    now=int(time.time())
    if "is_open" in columns:
        sets.append("is_open=0")
    if "status" in columns:
        sets.append("status=?"); params.append("closed")
    if "closed_at" in columns:
        sets.append("closed_at=?"); params.append(now)
    if "close_reason" in columns:
        sets.append("close_reason=?"); params.append("onchain_zero")
    # normalize qty fields if present
    for c in ("qty_token","qty","ui_qty","ui_amount","amount_ui"):
        if c in columns:
            sets.append(f"{c}=?"); params.append(0)
    if not sets:
        return None
    # choose key
    if "mint" in columns:
        where="mint=?"
    elif "input_mint" in columns:
        where="input_mint=?"
    else:
        return None
    sql=f"UPDATE {table} SET " + ", ".join(sets) + f" WHERE {where}"
    return (sql, params, where)

def main():
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row
    table=pick_positions_table(con)
    columns=cols(con, table)

    mint_col = "mint" if "mint" in columns else ("input_mint" if "input_mint" in columns else None)
    if not mint_col:
        raise SystemExit(f"FATAL: cannot find mint column in {table}. cols={columns}")

    where_sql, where_params = detect_open_where(columns)
    rows=con.execute(f"SELECT * FROM {table} WHERE {where_sql}", where_params).fetchall()
    print(f"positions_table={table} open_candidates={len(rows)} mint_col={mint_col}")

    upd=close_update_sql(table, columns)
    if not upd:
        print("WARN: cannot auto-close (no compatible columns). Showing mints with onchain=0 only.")
    else:
        upd_sql, upd_params_prefix, where_key = upd

    zero=[]
    for r in rows:
        mint=r[mint_col]
        ui=onchain_ui_balance(mint)
        if ui <= 0.0:
            zero.append(mint)
            if upd:
                # bind mint at end
                params=list(upd_params_prefix) + [mint]
                con.execute(upd_sql, params)

    if upd and zero:
        con.commit()

    print(f"onchain_zero_count={len(zero)}")
    for m in zero[:50]:
        print(" -", m)
    if len(zero) > 50:
        print(f" ... (+{len(zero)-50} more)")

if __name__=="__main__":
    main()
