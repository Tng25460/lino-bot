#!/usr/bin/env python3
import argparse
import base64
import json
import struct
import subprocess
import time
from typing import Any, Dict, Optional, Tuple

import requests
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.hash import Hash
from solders.instruction import Instruction, AccountMeta
from solders.message import Message
from solders.transaction import Transaction

TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

def rpc_call(rpc: str, method: str, params: list, timeout_s: int = 25) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(rpc, json=payload, timeout=timeout_s)
    r.raise_for_status()
    j = r.json()
    if "error" in j and j["error"]:
        raise RuntimeError(j["error"])
    return j.get("result")

def wait_sig(rpc: str, sig: str, timeout_s: int = 75, poll_s: float = 1.0) -> Dict[str, Any]:
    t0 = time.time()
    last = None
    while True:
        res = rpc_call(rpc, "getSignatureStatuses", [[sig], {"searchTransactionHistory": True}], timeout_s=25)
        v = (res or {}).get("value") or [None]
        st = v[0]
        if st:
            last = st
            cs = st.get("confirmationStatus")
            err = st.get("err")
            if cs:
                print("[confirm]", cs, "err=", err, flush=True)
            if cs in ("confirmed", "finalized"):
                return st
        if time.time() - t0 > timeout_s:
            raise TimeoutError({"sig": sig, "last": last})
        time.sleep(poll_s)

def solana_address(keypair_path: str) -> str:
    return subprocess.check_output(["solana", "address", "-k", keypair_path], text=True).strip()

def get_latest_blockhash(rpc: str) -> Hash:
    res = rpc_call(rpc, "getLatestBlockhash", [{"commitment": "confirmed"}], timeout_s=25)
    bh = res["value"]["blockhash"]
    return Hash.from_string(bh)

def get_token_account_for_mint(rpc: str, owner: str, mint: str) -> Optional[Tuple[str, int, int, float]]:
    # returns (token_account_pubkey, amount_base_units, decimals, ui)
    res = rpc_call(
        rpc,
        "getTokenAccountsByOwner",
        [
            owner,
            {"programId": str(TOKEN_PROGRAM_ID)},
            {"encoding": "jsonParsed"},
        ],
        timeout_s=25,
    )
    vals = (res or {}).get("value") or []
    for it in vals:
        info = it["account"]["data"]["parsed"]["info"]
        if info.get("mint") != mint:
            continue
        tok = info["tokenAmount"]
        amount = int(tok.get("amount") or "0")
        dec = int(tok.get("decimals") or 0)
        ui = float(tok.get("uiAmount") or 0.0)
        return (it["pubkey"], amount, dec, ui)
    return None

def ix_burn(source: Pubkey, mint: Pubkey, owner: Pubkey, amount: int) -> Instruction:
    # SPL-Token Burn: tag=8, amount=u64 LE
    data = struct.pack("<BQ", 8, amount)
    keys = [
        AccountMeta(pubkey=source, is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=owner, is_signer=True, is_writable=False),
    ]
    return Instruction(program_id=TOKEN_PROGRAM_ID, data=data, accounts=keys)

def ix_close_account(account: Pubkey, destination: Pubkey, owner: Pubkey) -> Instruction:
    # SPL-Token CloseAccount: tag=9
    data = struct.pack("<B", 9)
    keys = [
        AccountMeta(pubkey=account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=destination, is_signer=False, is_writable=True),
        AccountMeta(pubkey=owner, is_signer=True, is_writable=False),
    ]
    return Instruction(program_id=TOKEN_PROGRAM_ID, data=data, accounts=keys)

def main() -> int:
    ap = argparse.ArgumentParser(description="Burn remaining tokens and close the token account (ATA) for a mint.")
    ap.add_argument("--rpc", required=True, help="RPC HTTP endpoint (write-enabled)")
    ap.add_argument("--mint", required=True, help="Token mint to burn+close")
    ap.add_argument("--keypair", default="keypair.json", help="Signer keypair path (default: keypair.json)")
    ap.add_argument("--sig-timeout", type=int, default=75)
    args = ap.parse_args()

    rpc = args.rpc
    mint_str = args.mint
    kp_path = args.keypair

    owner_str = solana_address(kp_path)
    owner_pk = Pubkey.from_string(owner_str)
    mint_pk = Pubkey.from_string(mint_str)

    found = get_token_account_for_mint(rpc, owner_str, mint_str)
    if not found:
        print("[skip] no token account for mint (already closed?)", mint_str, flush=True)
        return 0

    acct_str, amount, dec, ui = found
    acct_pk = Pubkey.from_string(acct_str)

    print("[owner]", owner_str, flush=True)
    print("[acct] ", acct_str, flush=True)
    print("[mint] ", mint_str, flush=True)
    print("[ui]   ", ui, " [amount]", amount, " [dec]", dec, flush=True)

    # build tx
    ixs = []
    if amount > 0:
        ixs.append(ix_burn(acct_pk, mint_pk, owner_pk, amount))
    ixs.append(ix_close_account(acct_pk, owner_pk, owner_pk))

    bh = get_latest_blockhash(rpc)
    payer = owner_pk

    msg = Message.new_with_blockhash(ixs, payer, bh)
    kp = Keypair.from_json(open(kp_path, "r", encoding="utf-8").read())
    tx = Transaction.new_unsigned(msg)
    tx = tx.sign([kp], bh)

    raw = bytes(tx)
    tx_b64 = base64.b64encode(raw).decode("ascii")

    sig = rpc_call(
        rpc,
        "sendTransaction",
        [tx_b64, {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed"}],
        timeout_s=35,
    )
    print("[send] sig=", sig, flush=True)

    st = wait_sig(rpc, sig, timeout_s=args.sig_timeout, poll_s=1.0)
    if st.get("err"):
        raise SystemExit({"sig": sig, "err": st.get("err")})

    print("[OK] done", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
