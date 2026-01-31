import json
import time
import requests
from pathlib import Path

RPC = "https://api.mainnet-beta.solana.com"
JUP = "https://api.jup.ag"

PNL_FILE = Path("state/pnl_history.jsonl")
PNL_FILE.parent.mkdir(exist_ok=True)

def _rpc(method, params):
    r = requests.post(RPC, json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params
    }, timeout=20)
    r.raise_for_status()
    return r.json()["result"]

def get_token_balance(owner, mint):
    res = _rpc("getTokenAccountsByOwner", [
        owner,
        {"mint": mint},
        {"encoding": "jsonParsed"}
    ])
    total = 0.0
    for a in res["value"]:
        info = a["account"]["data"]["parsed"]["info"]
        total += float(info["tokenAmount"]["uiAmount"] or 0)
    return total

def get_price_sol(mint):
    r = requests.get(f"{JUP}/price/v2", params={"ids": mint}, timeout=15)
    r.raise_for_status()
    j = r.json()
    return float(j["data"][mint]["price"])

def log_snapshot(meta, label):
    mint = meta["mint"]
    owner = meta["user"]
    sol_in = meta["sol_in"]

    bal = get_token_balance(owner, mint)
    px = get_price_sol(mint)
    value_sol = bal * px
    pnl_pct = ((value_sol - sol_in) / sol_in) * 100 if sol_in > 0 else 0

    rec = {
        "ts": int(time.time()),
        "label": label,
        "mint": mint,
        "bal": bal,
        "px_sol": px,
        "value_sol": value_sol,
        "sol_in": sol_in,
        "pnl_pct": pnl_pct,
        "meta": meta,
    }
    with PNL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")

    print(f"📊 PNL {label}: {pnl_pct:.2f}% ({value_sol:.4f} SOL)")
