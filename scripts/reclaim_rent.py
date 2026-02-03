import os, json, time, base64
from typing import List
import requests

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.message import MessageV0
from solders.transaction import VersionedTransaction

RPC_URL = os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")
KEYPAIR_PATH = os.getenv("KEYPAIR_PATH", "/home/tng25/lino/keypair.json")

# keep some SOL to avoid getting stuck
MIN_SOL_BUFFER_SOL = float(os.getenv("MIN_SOL_BUFFER_SOL", "0.01"))
# number of token accounts to close per transaction
BATCH_SIZE = int(os.getenv("CLOSE_BATCH_SIZE", "4"))
# wait between tx
SLEEP_S = float(os.getenv("CLOSE_SLEEP_S", "0.2"))

TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

def jrpc(method, params):
    r = requests.post(RPC_URL, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=25)
    r.raise_for_status()
    out = r.json()
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]

def sol_balance(owner: str) -> float:
    lamports = jrpc("getBalance", [owner])["value"]
    return lamports / 1e9

def get_latest_blockhash() -> str:
    return jrpc("getLatestBlockhash", [{"commitment":"processed"}])["value"]["blockhash"]

def load_keypair() -> Keypair:
    arr = json.load(open(KEYPAIR_PATH, "r"))
    return Keypair.from_bytes(bytes(arr))

def list_empty_token_accounts(owner: str) -> List[str]:
    # SPL token accounts owned by wallet
    res = jrpc("getTokenAccountsByOwner", [owner, {"programId": str(TOKEN_PROGRAM_ID)}, {"encoding":"jsonParsed"}])
    empties = []
    for it in res.get("value", []):
        pubkey = it["pubkey"]
        info = it["account"]["data"]["parsed"]["info"]
        ui = info["tokenAmount"]["uiAmount"]
        # only close exact zero; do NOT close nonzero dust
        if ui == 0:
            empties.append(pubkey)
    return empties

def close_account_ix(token_account: Pubkey, owner: Pubkey) -> Instruction:
    # SPL Token CloseAccount instruction (9)
    # accounts: [token_account (writable), destination(owner) (writable), owner (signer)]
    data = bytes([9])  # CloseAccount
    metas = [
        AccountMeta(token_account, is_signer=False, is_writable=True),
        AccountMeta(owner, is_signer=False, is_writable=True),
        AccountMeta(owner, is_signer=True, is_writable=False),
    ]
    return Instruction(TOKEN_PROGRAM_ID, data, metas)

def send_tx(kp: Keypair, ixs: List[Instruction]) -> str:
    bh = get_latest_blockhash()
    payer = kp.pubkey()
    msg = MessageV0.try_compile(payer, ixs, [], bh)
    tx = VersionedTransaction(msg, [kp])
    b64 = base64.b64encode(bytes(tx)).decode("ascii")
    # use sendTransaction (base64), skip preflight false (more safe), confirmed
    res = jrpc("sendTransaction", [b64, {"encoding":"base64", "skipPreflight": False, "preflightCommitment":"processed"}])
    return str(res)

def confirm(sig: str, tries=25, sleep=0.6) -> bool:
    for _ in range(tries):
        st = jrpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])["value"][0]
        if st and st.get("confirmationStatus") in ("confirmed","finalized"):
            err = st.get("err")
            return err is None
        time.sleep(sleep)
    return False

def main():
    kp = load_keypair()
    owner = str(kp.pubkey())

    sol0 = sol_balance(owner)
    empties = list_empty_token_accounts(owner)
    print(f"[RECLAIM] owner={owner}")
    print(f"[RECLAIM] SOL start={sol0:.6f}")
    print(f"[RECLAIM] empty token accounts: {len(empties)}")

    if not empties:
        print("[RECLAIM] nothing to close")
        return

    closed = 0
    for i in range(0, len(empties), BATCH_SIZE):
        sol = sol_balance(owner)
        if sol < MIN_SOL_BUFFER_SOL:
            print(f"[RECLAIM] STOP: SOL {sol:.6f} < buffer {MIN_SOL_BUFFER_SOL:.6f}")
            break

        batch = empties[i:i+BATCH_SIZE]
        ixs = [close_account_ix(Pubkey.from_string(a), kp.pubkey()) for a in batch]

        try:
            sig = send_tx(kp, ixs)
            ok = confirm(sig)
            print(f"[RECLAIM] txsig={sig} ok={ok} closed_batch={len(batch)}")
            if ok:
                closed += len(batch)
        except Exception as e:
            print(f"[RECLAIM] ERROR batch_start={i} err={e}")
            # continue with next batch
        time.sleep(SLEEP_S)

    sol1 = sol_balance(owner)
    print(f"[RECLAIM] DONE closed={closed}/{len(empties)} SOL end={sol1:.6f} delta={sol1-sol0:+.6f}")

if __name__ == "__main__":
    main()
