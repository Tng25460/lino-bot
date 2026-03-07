import os, json, sqlite3, requests, time

DB_PATH = os.getenv("DB_PATH", "state/trades.sqlite")
RPC_HTTP = os.getenv("RPC_HTTP") or os.getenv("SOLANA_RPC_HTTP") or "https://api.mainnet-beta.solana.com"
WALLET = os.getenv("WALLET_PUBKEY") or os.getenv("TRADER_USER_PUBLIC_KEY")
DUST_UI = float(os.getenv("DUST_UI", "0.000001") or 0.000001)
SLEEP_S = float(os.getenv("SLEEP_S", "0.12") or 0.12)

if not WALLET:
    raise SystemExit("ERROR: WALLET_PUBKEY not set (source state/live.env first)")

def rpc(method, params):
    r = requests.post(RPC_HTTP, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=30)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j["result"]

def ui_balance_for_mint(owner_pubkey: str, mint: str) -> float:
    # parsed accounts -> easiest uiAmount
    res = rpc("getTokenAccountsByOwner", [
        owner_pubkey,
        {"mint": mint},
        {"encoding": "jsonParsed"}
    ])
    total = 0.0
    for it in (res.get("value") or []):
        try:
            info = it["account"]["data"]["parsed"]["info"]
            amt = info["tokenAmount"].get("uiAmount")
            if amt is None:
                # uiAmountString fallback
                s = info["tokenAmount"].get("uiAmountString") or "0"
                amt = float(s)
            total += float(amt or 0.0)
        except Exception:
            continue
    return float(total)

def open_mints(conn):
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT mint, qty_token
        FROM positions
        WHERE lower(coalesce(status,''))='open'
        ORDER BY entry_ts ASC
    """).fetchall()
    return [(m, float(q or 0.0)) for (m,q) in rows]

def close_db(conn, mint, reason):
    cur = conn.cursor()
    cur.execute("""
        UPDATE positions
        SET status='closed', close_reason=?, close_ts=strftime('%s','now')
        WHERE mint=? AND lower(coalesce(status,''))='open'
    """, (reason, mint))
    conn.commit()

def main():
    conn = sqlite3.connect(DB_PATH)
    mints = open_mints(conn)
    print(f"OPEN_DB={len(mints)} RPC={RPC_HTTP} WALLET={WALLET} DUST_UI={DUST_UI}", flush=True)

    kept = 0
    closed = 0
    for mint, db_qty in mints:
        try:
            ui = ui_balance_for_mint(WALLET, mint)
        except Exception as e:
            print(f"[RPC_FAIL] mint={mint} err={e}", flush=True)
            time.sleep(SLEEP_S)
            continue

        if ui <= DUST_UI:
            close_db(conn, mint, "onchain_zero_or_dust")
            closed += 1
            print(f"[CLOSE_DB] mint={mint} onchain_ui={ui} db_qty={db_qty}", flush=True)
        else:
            kept += 1
            print(f"[KEEP] mint={mint} onchain_ui={ui} db_qty={db_qty}", flush=True)

        time.sleep(SLEEP_S)

    conn.close()
    print(f"DONE kept_open={kept} closed={closed}", flush=True)

if __name__ == "__main__":
    main()
