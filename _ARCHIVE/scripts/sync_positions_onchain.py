import os, json, time, sqlite3, requests
from solders.keypair import Keypair

DB=os.getenv("DB_PATH","state/trades.sqlite")
RPC=os.getenv("SOLANA_RPC","https://api.mainnet-beta.solana.com")

secret=json.load(open(os.getenv("KEYPAIR_PATH","keypair.json"), "r", encoding="utf-8"))
kp=Keypair.from_bytes(bytes(secret))
OWNER=str(kp.pubkey())

def onchain_ui(mint: str) -> float:
    payload={"jsonrpc":"2.0","id":1,"method":"getTokenAccountsByOwner",
             "params":[OWNER,{"mint":mint},{"encoding":"jsonParsed"}]}
    r=requests.post(RPC, json=payload, timeout=25).json()
    if "error" in r:
        raise RuntimeError(r["error"])
    total=0.0
    for a in r.get("result",{}).get("value",[]):
        info=a["account"]["data"]["parsed"]["info"]
        ui=info["tokenAmount"]["uiAmount"] or 0
        total += float(ui)
    return total

con=sqlite3.connect(DB, timeout=30)
con.row_factory=sqlite3.Row
cur=con.cursor()

rows=cur.execute("""
  SELECT rowid,mint,symbol,qty_token,tp1_done,tp2_done
  FROM positions
  WHERE lower(status)='open'
  ORDER BY entry_ts ASC
""").fetchall()

print("RPC  :", RPC)
print("OWNER:", OWNER)
print("OPEN positions:", len(rows))

closed=0
for r in rows:
    mint=r["mint"]
    sym=r["symbol"] or mint[:6]
    dbq=float(r["qty_token"] or 0.0)

    try:
        oc=onchain_ui(mint)
    except Exception as e:
        print(f"❌ onchain fetch failed {sym} mint={mint} err={e}")
        continue

    print(f"- {sym:10} db_qty={dbq:.6f} onchain_ui={oc:.6f} mint={mint}")

    if oc <= 0.0:
        now=time.time()
        cur.execute("""
          UPDATE positions
          SET status='CLOSED',
              close_ts=?,
              close_reason='SYNC_ONCHAIN_ZERO'
          WHERE rowid=?
        """,(now, r["rowid"]))
        closed += cur.rowcount

con.commit()
con.close()
print("✅ closed_by_sync:", closed)
