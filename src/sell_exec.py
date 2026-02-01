#!/usr/bin/env python3
import os

# JUP_CUSTOM_ERROR_CODES: classify some Jupiter on-chain custom errors (avoid infinite retries)
JUP_CUSTOM_ERROR_CODES = {6024, 6025}

def _extract_custom_code(err_obj):
    """
    Try to extract Custom code from Solana RPC error dict:
    err: {'InstructionError': [idx, {'Custom': 6024}]}
    """
    try:
        if isinstance(err_obj, dict) and "InstructionError" in err_obj:
            ie = err_obj["InstructionError"]
            if isinstance(ie, list) and len(ie) == 2 and isinstance(ie[1], dict) and "Custom" in ie[1]:
                return int(ie[1]["Custom"])
    except Exception:
        pass
    return None
import sys
import json
import time
import base64
import argparse

def _rpc_get_balance_lamports(rpc_url: str, pubkey: str) -> int:
    import requests
    payload = {"jsonrpc":"2.0","id":1,"method":"getBalance","params":[pubkey, {"commitment":"processed"}]}
    r = requests.post(rpc_url, json=payload, timeout=15)
    r.raise_for_status()
    j = r.json()
    return int((j.get("result") or {}).get("value") or 0)

def _precheck_min_sol_fees(rpc_url: str, pubkey: str) -> bool:
    # default: 0.02 SOL
    import os
    min_sol = float(os.getenv("SELL_MIN_SOL_FEES", "0.02"))
    lamports = _rpc_get_balance_lamports(rpc_url, pubkey)
    sol = lamports / 1_000_000_000
    if sol < min_sol:
        print(f"⚠️ LOW_SOL_FEES sol={sol:.6f} < min={min_sol} -> SKIP sell", flush=True)
        return False
    return True




def _with_401_fallback(do_request, base_url: str):
    """
    do_request(base_url) -> response (requests)
    Si 401 sur api.jup.ag, on retente lite-api.
    Si 401 sur lite-api, on retente api.jup.ag.
    """
    try:
        r = do_request(base_url)
        if getattr(r, "status_code", None) != 401:
            return r, base_url
    except Exception:
        raise

    alt = "https://lite-api.jup.ag" if "api.jup.ag" in base_url else "https://api.jup.ag"
    r2 = do_request(alt)
    return r2, alt
from decimal import Decimal, ROUND_DOWN

import requests
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

SOL_MINT = "So11111111111111111111111111111111111111112"

def rpc_call(rpc: str, method: str, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(rpc, json=payload, timeout=30)
    j = r.json()
    if "error" in j and j["error"]:
        raise RuntimeError(f"RPC error: {j['error']}")
    return j["result"]

def send_tx(rpc: str, tx_b64: str) -> str:
    res = rpc_call(
        rpc,
        "sendTransaction",
        [tx_b64, {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "processed"}],
    )
    # can be string sig, or dict in some setups
    if isinstance(res, str):
        return res
    if isinstance(res, dict) and "result" in res:
        return res["result"]
    # fallback
    return str(res)

def confirm_sig(rpc: str, sig: str, timeout_s: int = 35):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        st = rpc_call(rpc, "getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])
        v = (st.get("value") or [None])[0]
        if v is not None:
            if v.get("err") is not None:
                raise RuntimeError(f"confirm err={v.get('err')}")
            conf = v.get("confirmationStatus")
            if conf in ("processed", "confirmed", "finalized"):
                return conf
        time.sleep(1.0)
    raise RuntimeError("confirm timeout")

def get_decimals(rpc: str, mint: str) -> int:
    res = rpc_call(rpc, "getTokenSupply", [mint, {"commitment": "processed"}])
    # res: { context, value: { amount, decimals, uiAmountString } }
    return int(res["value"]["decimals"])

def jup_quote(base: str, input_mint: str, output_mint: str, amount: int, slippage_bps: int):
    url = base.rstrip("/") + "/swap/v1/quote"
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount),
        "slippageBps": str(slippage_bps),
        "swapMode": "ExactIn",
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def jup_swap(base: str, quote: dict, user_pubkey: str):
    url = base.rstrip("/") + "/swap/v1/swap"
    body = {
        "quoteResponse": quote,
        "userPublicKey": user_pubkey,
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
    }
    r = requests.post(url, json=body, timeout=60)
    r.raise_for_status()
    return r.json()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mint", required=True)
    ap.add_argument("--ui", required=True, help="UI amount to sell (token units)")
    ap.add_argument("--reason", default="manual")
    args = ap.parse_args()

    base = os.getenv("JUP_BASE_URL", "https://lite-api.jup.ag").rstrip("/")
    rpc = os.getenv("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
    slippage_bps = int(os.getenv("SELL_SLIPPAGE_BPS", os.getenv("SLIPPAGE_BPS", "300")))
    dry = os.getenv("SELL_DRY_RUN", "0") == "1"

    keypath = os.getenv("KEYPAIR_PATH", "keypair.json")
    secret = json.load(open(keypath, "r", encoding="utf-8"))
    kp = Keypair.from_bytes(bytes(secret))
    owner = str(kp.pubkey())

    ui_amt = Decimal(args.ui)
    dec = get_decimals(rpc, args.mint)

    amt = int((ui_amt * (Decimal(10) ** dec)).quantize(Decimal("1"), rounding=ROUND_DOWN))
    if amt <= 0:
        raise SystemExit("computed amount <= 0 (check decimals/ui)")

    print(
        f"SELL_EXEC reason={args.reason} mint={args.mint} ui={ui_amt} dec={dec} amount={amt} "
        f"slippage_bps={slippage_bps} base={base} rpc={rpc} dry={dry}",
        flush=True,
    )

    quote = jup_quote(base, args.mint, SOL_MINT, amt, slippage_bps)
    swap = jup_swap(base, quote, owner)

    tx_b64 = swap.get("swapTransaction")
    if not tx_b64:
        raise RuntimeError(f"no swapTransaction in response: keys={list(swap.keys())}")

    if dry:
        print("DRY_RUN swapTransaction_len=", len(tx_b64), flush=True)
        print("txsig=DRY_RUN_NO_TX_SENT", flush=True)
        return

    raw = base64.b64decode(tx_b64)
    vtx = VersionedTransaction.from_bytes(raw)

    # canonical solders signing for v0:
    signed_vtx = VersionedTransaction(vtx.message, [kp])
    signed_b64 = base64.b64encode(bytes(signed_vtx)).decode("utf-8")

    txsig = send_tx(rpc, signed_b64)
    print("txsig=" + txsig, flush=True)

    # confirm (non-fatal warning)
    try:
        st = confirm_sig(rpc, txsig, timeout_s=int(os.getenv("SELL_CONFIRM_TIMEOUT_S", "35")))
        print("confirm=" + str(st), flush=True)
    except Exception as e:
    # EXIT42_ON_CUSTOM
    try:
        err_obj = None
        if isinstance(e, dict) and 'data' in e and isinstance(e['data'], dict) and 'err' in e['data']:
            err_obj = e['data']['err']
        code = _extract_custom_code(err_obj)
        if code in JUP_CUSTOM_ERROR_CODES:
            print(f"⚠️ JUP_CUSTOM_CODE {code} -> exit 42 (cooldown)")
            import sys
            sys.exit(42)
    except SystemExit:
        raise
    except Exception:
        pass
        print("WARN confirm:", e, flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("FATAL:", e, flush=True)
        sys.exit(1)
