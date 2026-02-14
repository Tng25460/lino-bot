import os, math, sqlite3, requests, time

DB = os.getenv("TRADES_DB", "state/trades.sqlite")
RPC = os.getenv("RPC_HTTP", "https://api.mainnet-beta.solana.com")
JUP = os.getenv("JUP_BASE_URL", "https://lite-api.jup.ag").rstrip("/")
SOL_MINT = "So11111111111111111111111111111111111111112"

def rpc(method, params):
    r = requests.post(RPC, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=25)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j["result"]

def get_decimals(mint: str) -> int:
    res = rpc("getTokenSupply", [mint])
    return int(res["value"]["decimals"])

def jup_price_sol_per_token(mint: str, ui_amt: float, decimals: int) -> float:
    # quote token -> SOL
    amt = int(max(1, round(ui_amt * (10 ** decimals))))
    url = f"{JUP}/swap/v1/quote"
    params = {
        "inputMint": mint,
        "outputMint": SOL_MINT,
        "amount": str(amt),
        "slippageBps": "120",
    }
    r = requests.get(url, params=params, timeout=25)
    if r.status_code != 200:
        raise RuntimeError(f"jup_quote_http={r.status_code} body={r.text[:200]}")
    q = r.json()
    out_amt = int(q.get("outAmount") or 0)  # lamports
    if out_amt <= 0:
        raise RuntimeError("outAmount<=0")
    out_sol = out_amt / 1e9
    price = out_sol / ui_amt
    return float(price)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

cur.execute("SELECT id, mint, qty_token, entry_price, status FROM positions WHERE status='OPEN' ORDER BY id DESC")
rows = cur.fetchall()
todo = [r for r in rows if (r["entry_price"] is None or float(r["entry_price"] or 0.0) <= 0.0)]

print(f"[backfill_entry] DB={DB}")
print(f"[backfill_entry] RPC={RPC}")
print(f"[backfill_entry] JUP={JUP}")
print(f"[backfill_entry] open_positions={len(rows)} entry0_positions={len(todo)}")

updated = 0
for r in todo:
    pid = int(r["id"])
    mint = str(r["mint"])
    qty = float(r["qty_token"] or 0.0)
    if qty <= 0:
        print(f"[backfill_entry] skip id={pid} mint={mint} qty_token<=0")
        continue

    # test quote with a small UI amount to avoid huge amounts / route issues
    ui_test = min(qty, 250.0)
    try:
        dec = get_decimals(mint)
        px = jup_price_sol_per_token(mint, ui_test, dec)
        if not (px > 0 and math.isfinite(px)):
            raise RuntimeError("bad price")
        cur.execute("UPDATE positions SET entry_price=? WHERE id=?", (px, pid))
        updated += 1
        print(f"[backfill_entry] OK id={pid} mint={mint} entry_price_sol={px:.12g} (ui_test={ui_test} dec={dec})")
        time.sleep(0.15)
    except Exception as e:
        print(f"[backfill_entry] WARN id={pid} mint={mint} err={e}")

con.commit()
con.close()
print(f"[backfill_entry] DONE updated={updated}")
