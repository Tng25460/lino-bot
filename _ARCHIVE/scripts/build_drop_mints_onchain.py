#!/usr/bin/env python3
import os, time, requests

RPC=os.getenv("RPC_HTTP","https://api.mainnet-beta.solana.com").strip()
OWNER=(os.getenv("WALLET_PUBKEY","").strip()
       or os.getenv("TRADER_USER_PUBLIC_KEY","").strip()
       or os.getenv("SELL_OWNER_PUBKEY","").strip())
OUT=os.getenv("DROP_OUT","state/drop_mints_onchain.txt")
TIMEOUT=float(os.getenv("RPC_TIMEOUT","20"))

TOKEN_V1="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022="TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

def rpc(method, params):
    payload={"jsonrpc":"2.0","id":1,"method":method,"params":params}
    r=requests.post(RPC, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    j=r.json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j["result"]

def fetch_program(program_id: str):
    res = rpc("getTokenAccountsByOwner", [OWNER, {"programId": program_id}, {"encoding":"jsonParsed"}])
    vals = res.get("value", []) if isinstance(res, dict) else []
    held=[]
    for v in vals:
        acc = (v.get("account") or {}).get("data") or {}
        parsed = (acc.get("parsed") or {}).get("info") or {}
        mint = parsed.get("mint")
        ta = parsed.get("tokenAmount") or {}
        ui = ta.get("uiAmount")
        try:
            ui = float(ui) if ui is not None else 0.0
        except Exception:
            ui = 0.0
        if mint and ui > 0:
            held.append((mint, ui))
    return held

def main():
    if not OWNER:
        raise SystemExit("missing WALLET_PUBKEY (or TRADER_USER_PUBLIC_KEY / SELL_OWNER_PUBKEY)")

    held_map = {}  # mint -> ui (max across programs)
    for pid in (TOKEN_V1, TOKEN_2022):
        for mint, ui in fetch_program(pid):
            prev = held_map.get(mint, 0.0)
            if ui > prev:
                held_map[mint] = ui

    held = sorted(held_map.items(), key=lambda x: x[1], reverse=True)

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f:
        f.write("# auto-generated on-chain holdings drop list (token + token2022)\n")
        f.write(f"# ts={int(time.time())} owner={OWNER} rpc={RPC}\n")
        for mint,_ui in held:
            f.write(mint+"\n")

    print(f"[OK] holdings={len(held)} -> {OUT}")
    for mint, ui in held[:20]:
        print(" ", mint, "ui=", ui)

if __name__=="__main__":
    main()
