import os, json, time, sqlite3, urllib.request, urllib.error

RPC=os.environ["RPC_URL"]
DB=os.environ["DB_PATH"]
WALLET=os.environ["WALLET_PUBKEY"]

SLEEP_BETWEEN=float(os.environ.get("RECONCILE_SLEEP_S","0.25"))
MAX_RETRY=int(os.environ.get("RECONCILE_MAX_RETRY","10"))

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
                backoff = min(8.0, 0.5 * (2**attempt))
                print(f"[429] {method} backoff={backoff:.2f}s attempt={attempt+1}/{MAX_RETRY}")
                time.sleep(backoff)
                continue
            raise
        except Exception as e:
            backoff = min(5.0, 0.25 * (2**attempt))
            print(f"[ERR] {method} {type(e).__name__}: {e} backoff={backoff:.2f}s attempt={attempt+1}/{MAX_RETRY}")
            time.sleep(backoff)
    raise RuntimeError(f"RPC {method} failed after {MAX_RETRY} retries")

def onchain_ui_balance(mint: str) -> float:
    res=rpc_call("getTokenAccountsByOwner", [WALLET, {"mint": mint}, {"encoding":"jsonParsed","commitment":"processed"}])
    vals=(res.get("result") or {}).get("value") or []
    ui=0.0
    for v in vals:
        info=v["account"]["data"]["parsed"]["info"]
        amt=info["tokenAmount"]
        s=amt.get("uiAmountString")
        if s is None:
            ui += float(amt.get("uiAmount") or 0.0)
        else:
            try: ui += float(s)
            except: pass
    return ui

def table_exists(con, name):
    r=con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return bool(r)

def cols(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]

def detect_open_where(columns):
    if "is_open" in columns: return ("is_open=1", ())
    if "status" in columns: return ("status IN ('open','OPEN','active','ACTIVE')", ())
    if "closed_at" in columns: return ("(closed_at IS NULL OR closed_at=0 OR closed_at='')", ())
    return ("1=1", ())

def close_update_sql(table, columns):
    sets=[]
    params=[]
    now=int(time.time())
    if "is_open" in columns: sets.append("is_open=0")
    if "status" in columns: sets.append("status=?"); params.append("closed")
    if "closed_at" in columns: sets.append("closed_at=?"); params.append(now)
    if "close_reason" in columns: sets.append("close_reason=?"); params.append("onchain_zero")
    for c in ("qty_token","qty","ui_qty","ui_amount","amount_ui"):
        if c in columns:
            sets.append(f"{c}=?"); params.append(0)
    if not sets: return None
    if "mint" in columns:
        where="mint=?"
    elif "input_mint" in columns:
        where="input_mint=?"
    else:
        return None
    sql=f"UPDATE {table} SET " + ", ".join(sets) + f" WHERE {where}"
    return (sql, params)

def main():
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row

    if not table_exists(con, "positions"):
        raise SystemExit("FATAL: positions table not found in DB")

    table="positions"
    columns=cols(con, table)
    mint_col = "mint" if "mint" in columns else ("input_mint" if "input_mint" in columns else None)
    if not mint_col:
        raise SystemExit(f"FATAL: cannot find mint column in {table}. cols={columns}")

    where_sql, where_params = detect_open_where(columns)
    rows=con.execute(f"SELECT * FROM {table} WHERE {where_sql}", where_params).fetchall()
    print(f"positions_table={table} open_candidates={len(rows)} mint_col={mint_col}")

    upd=close_update_sql(table, columns)
    if not upd:
        print("WARN: cannot auto-close (no compatible columns) -> dry listing only")

    upd_sql, upd_prefix = upd if upd else (None, None)

    zero=[]
    ok=0
    for idx,r in enumerate(rows, 1):
        mint=r[mint_col]
        try:
            ui=onchain_ui_balance(mint)
            ok += 1
        except Exception as e:
            print(f"[SKIP_ERR] mint={mint} err={type(e).__name__}: {e}")
            continue

        if ui <= 0.0:
            zero.append(mint)
            if upd_sql:
                con.execute(upd_sql, list(upd_prefix) + [mint])

        if SLEEP_BETWEEN > 0:
            time.sleep(SLEEP_BETWEEN)

        if idx % 10 == 0:
            print(f"[PROGRESS] {idx}/{len(rows)} rpc_ok={ok} zero={len(zero)}")

    if upd_sql and zero:
        con.commit()

    print(f"onchain_zero_count={len(zero)}")
    for m in zero[:80]:
        print(" -", m)
    if len(zero) > 80:
        print(f" ... (+{len(zero)-80} more)")

if __name__=="__main__":
    main()
