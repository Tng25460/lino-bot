import os, time, sqlite3, random
import requests

DB = os.getenv("TRADES_DB_PATH", os.getenv("DB_PATH", "state/trades.sqlite"))
RPC = os.getenv("RPC_HTTP", "https://api.mainnet-beta.solana.com")
OWNER = os.getenv("WALLET_PUBKEY") or os.getenv("TRADER_USER_PUBLIC_KEY")

WINDOW_SEC = int(os.getenv("BUY_QTY_RESYNC_WINDOW_SEC", "900"))
RESYNC_ALL_OPEN = os.getenv("RESYNC_ALL_OPEN", "0") == "1"

TRIES = int(os.getenv("BUY_QTY_RESYNC_TRIES", "8"))
BASE_SLEEP = float(os.getenv("BUY_QTY_RESYNC_BASE_SLEEP", "1.6"))
MAX_SLEEP = float(os.getenv("BUY_QTY_RESYNC_MAX_SLEEP", "8.0"))

if not OWNER:
    print("❌ resync_buy_qty: missing WALLET_PUBKEY/TRADER_USER_PUBLIC_KEY", flush=True)
    raise SystemExit(0)

def rpc(method, params, timeout=20):
    r = requests.post(
        RPC,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=timeout,
    )
    if r.status_code == 429:
        raise RuntimeError("RPC_429")
    r.raise_for_status()
    j = r.json()
    if isinstance(j, dict) and j.get("error"):
        raise RuntimeError(str(j["error"]))
    return j.get("result")

def ui_balance_for_mint(owner, mint):
    res = rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}], timeout=20)
    total = 0.0
    for it in (res or {}).get("value", []) or []:
        try:
            info = it["account"]["data"]["parsed"]["info"]
            amt = info["tokenAmount"]
            total += float(amt.get("uiAmount") or 0.0)
        except Exception:
            pass
    return float(total)

def wait_ui(owner, mint):
    last = 0.0
    for k in range(TRIES):
        try:
            ui = ui_balance_for_mint(owner, mint)
            last = ui
            if ui > 0.0:
                return ui
        except Exception as e:
            if "RPC_429" in str(e) or "429" in str(e):
                pass
        sleep_s = min(MAX_SLEEP, BASE_SLEEP * (1.6 ** k)) + random.random() * 0.25
        time.sleep(sleep_s)
    return last

now = int(time.time())
cut = 0 if RESYNC_ALL_OPEN else (now - WINDOW_SEC)

print(f"🔎 resync_buy_qty: owner={OWNER} db={DB} window_s={WINDOW_SEC} resync_all_open={int(RESYNC_ALL_OPEN)}", flush=True)

con = sqlite3.connect(DB)
cur = con.cursor()

qty_clause = "" if RESYNC_ALL_OPEN else " AND COALESCE(qty_token,0)<=0.0"
sql = (
    "SELECT id, mint, entry_ts "
    "FROM positions "
    "WHERE status LIKE 'OPEN%'"
    + qty_clause +
    " AND COALESCE(entry_ts,0) >= ? "
    "ORDER BY id DESC"
)

rows = cur.execute(sql, (cut,)).fetchall()

updated = 0
closed = 0
failed = 0

for _id, mint, entry_ts in rows:
    try:
        ui = wait_ui(OWNER, mint)
        if ui and ui > 0.0:
            cur.execute("UPDATE positions SET qty_token=? WHERE id=?", (float(ui), _id))

            # if entry_price==0, derive from trades.qty (SOL spent) / qty_ui (token got)
            try:
                row = cur.execute(
                    "SELECT qty FROM trades WHERE side='BUY' AND mint=? AND ts=? ORDER BY id DESC LIMIT 1",
                    (mint, entry_ts),
                ).fetchone()
                sol_spent = float(row[0]) if row and row[0] is not None else 0.0
                if sol_spent > 0.0 and float(ui) > 0.0:
                    px = sol_spent / float(ui)
                    cur.execute(
                        "UPDATE positions SET entry_price=? WHERE id=? AND COALESCE(entry_price,0)=0",
                        (px, _id),
                    )
                    cur.execute(
                        "UPDATE trades SET price=? WHERE side='BUY' AND mint=? AND ts=? AND COALESCE(price,0)=0",
                        (px, mint, entry_ts),
                    )
            except Exception:
                pass

            con.commit()
            updated += 1
            print(f"✅ resync_buy_qty: id={_id} mint={mint[:8]}… ui={ui}", flush=True)
        else:
            cur.execute(
                "UPDATE positions SET status='CLOSED', close_ts=?, close_reason=? WHERE id=?",
                (now, "buy_qty_resync_failed", _id),
            )
            con.commit()
            closed += 1
            print(f"🧹 resync_buy_qty: CLOSED id={_id} mint={mint[:8]}… reason=buy_qty_resync_failed", flush=True)

    except Exception as e:
        failed += 1
        print(f"⚠️ resync_buy_qty: id={_id} mint={mint[:8]}… err={e}", flush=True)

con.close()
print(f"resync_buy_qty: updated={updated} closed={closed} failed={failed}", flush=True)
