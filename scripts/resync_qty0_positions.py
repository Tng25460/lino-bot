import os, json, time, sqlite3
import requests

DB = os.getenv("TRADES_DB", "state/trades.sqlite")
RPC = os.getenv("RPC_HTTP", "https://api.mainnet-beta.solana.com")

# wallet pubkey (env already used in your launchers)
WALLET = os.getenv("WALLET_PUBKEY") or os.getenv("TRADER_USER_PUBLIC_KEY")
if not WALLET:
    raise SystemExit("❌ missing WALLET_PUBKEY/TRADER_USER_PUBLIC_KEY")

def rpc(method, params):
    r = requests.post(RPC, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=25)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j["result"]

def ui_balance_for_mint(owner_pubkey: str, mint: str) -> float:
    # parsed token accounts for this mint
    res = rpc("getTokenAccountsByOwner", [
        owner_pubkey,
        {"mint": mint},
        {"encoding": "jsonParsed"}
    ])
    total = 0.0
    for it in res.get("value", []):
        info = it.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
        tok = info.get("tokenAmount", {}) or {}
        try:
            total += float(tok.get("uiAmount") or 0.0)
        except Exception:
            pass
    return float(total)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

cur.execute("SELECT id, mint, qty_token, entry_price, status FROM positions WHERE status='OPEN' ORDER BY id DESC")
rows = cur.fetchall()

todo = [r for r in rows if (r["qty_token"] is None or float(r["qty_token"] or 0.0) <= 0.0)]
print(f"[resync_qty0] DB={DB} RPC={RPC} wallet={WALLET}")
print(f"[resync_qty0] open_positions={len(rows)} qty0_positions={len(todo)}")

updated = 0
for r in todo:
    pid = r["id"]
    mint = r["mint"]
    try:
        ui = ui_balance_for_mint(WALLET, mint)
        print(f"[resync_qty0] id={pid} mint={mint} onchain_ui={ui}")
        if ui > 0:
            cur.execute("UPDATE positions SET qty_token=? WHERE id=?", (ui, pid))
            updated += 1
        else:
            # if zero on-chain too, leave it (could be already sold / dust / missing ATA)
            pass
    except Exception as e:
        print(f"[resync_qty0] WARN id={pid} mint={mint} err={e}")

con.commit()
con.close()
print(f"[resync_qty0] DONE updated={updated}")
