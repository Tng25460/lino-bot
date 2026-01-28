import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests


RPC_HTTP = os.getenv("SOLANA_RPC_HTTP", "https://api.mainnet-beta.solana.com").strip()

# input = tx signée en base64
SIGNED_TX_B64_PATH = Path(os.getenv("TRADER_SIGNED_TX_B64_PATH", "last_swap_tx.signed.b64"))

# options
COMMITMENT = os.getenv("TRADER_SIM_COMMITMENT", "processed")  # processed / confirmed / finalized
REPLACE_BLOCKHASH = os.getenv("TRADER_SIM_REPLACE_BLOCKHASH", "1") == "1"  # important si blockhash expiré


def rpc_call(method: str, params: Any) -> Dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(RPC_HTTP, json=payload, timeout=30)
    try:
        j = r.json()
    except Exception:
        raise SystemExit(f"[RPC] non-json http={r.status_code} body={r.text[:500]}")
    if "error" in j:
        raise SystemExit(f"[RPC][ERROR] {json.dumps(j['error'], ensure_ascii=False)}")
    return j


def main() -> None:
    if not SIGNED_TX_B64_PATH.exists():
        raise SystemExit(f"❌ signed tx missing: {SIGNED_TX_B64_PATH}")

    tx_b64 = SIGNED_TX_B64_PATH.read_text(encoding="utf-8").strip()
    # sanity decode
    try:
        raw = base64.b64decode(tx_b64)
    except Exception as e:
        raise SystemExit(f"❌ invalid base64 in {SIGNED_TX_B64_PATH}: {e}")

    print("🚀 simulate démarré")
    print("   rpc_http=", RPC_HTTP)
    print("   signed_file=", str(SIGNED_TX_B64_PATH))
    print("   tx_bytes=", len(raw))
    print("   commitment=", COMMITMENT, "replaceRecentBlockhash=", REPLACE_BLOCKHASH)

    # simulateTransaction expects base64 string
    # encoding="base64" is explicit in newer RPC
    params = [
        tx_b64,
        {
            "encoding": "base64",
            "sigVerify": (not REPLACE_BLOCKHASH),
            "replaceRecentBlockhash": REPLACE_BLOCKHASH,
            "commitment": COMMITMENT,
        },
    ]

    j = rpc_call("simulateTransaction", params)
    res = j.get("result") or {}
    val = res.get("value") or {}
    err = val.get("err")

    logs = val.get("logs") or []
    units = val.get("unitsConsumed")
    accounts = val.get("accounts")

    print("\n✅ simulate ok (RPC response reçue)")
    print("   err=", err)
    print("   unitsConsumed=", units)

    if logs:
        print("\n--- logs (last 60) ---")
        for line in logs[-60:]:
            print(line)

    # If you want to inspect accounts later, keep it minimal here
    if accounts is not None:
        print("\n(accounts returned:", len(accounts), ")")

    if err:
        print("\n🛑 SIMULATION FAILED -> rien n'a été envoyé (normal).")
        # Print full result for debugging (compact)
        print(json.dumps(val, ensure_ascii=False)[:4000])
    else:
        print("\n🎯 SIMULATION PASSED -> prêt à envoyer (mais on n'envoie PAS ici).")


if __name__ == "__main__":
    main()
