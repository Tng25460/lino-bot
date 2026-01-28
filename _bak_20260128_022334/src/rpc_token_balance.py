import json
import os
import requests
from typing import Optional, Tuple

RPC = (os.getenv("SOLANA_RPC_HTTP") or "https://api.mainnet-beta.solana.com").strip()

def _rpc(method: str, params: list):
    r = requests.post(RPC, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=25)
    r.raise_for_status()
    j = r.json()
    if "error" in j and j["error"]:
        raise RuntimeError(json.dumps(j["error"]))
    return j.get("result")

def get_token_ui_amount(owner: str, mint: str) -> Tuple[float, int]:
    # retourne (ui_amount, decimals)
    res = _rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding":"jsonParsed"}])
    value = (res or {}).get("value") or []
    total_ui = 0.0
    dec = 0
    for it in value:
        info = (((it.get("account") or {}).get("data") or {}).get("parsed") or {}).get("info") or {}
        ta = info.get("tokenAmount") or {}
        dec = int(ta.get("decimals") or dec)
        ui = float(ta.get("uiAmount") or 0.0)
        total_ui += ui
    return total_ui, dec
