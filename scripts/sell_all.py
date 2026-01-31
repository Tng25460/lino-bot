import os, json, time, base64
import requests
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

SOL_MINT = "So11111111111111111111111111111111111111112"

RPC_HTTP = os.getenv("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
JUP_BASE = os.getenv("JUP_BASE_URL", "https://lite-api.jup.ag")
KEYPAIR_PATH = os.getenv("KEYPAIR_PATH", "keypair.json")

SLIPPAGE_BPS = int(os.getenv("SELL_ALL_SLIPPAGE_BPS", "600"))  # 6% par défaut (tokens poubelle => routes dures)
MIN_UI = float(os.getenv("SELL_ALL_MIN_UI", "0.000001"))       # ignore poussière
DRY_RUN = os.getenv("SELL_ALL_DRY_RUN", "1") == "1"

# Denylist facultative: mints séparés par virgule à ne PAS vendre
DENY = {m.strip() for m in (os.getenv("SELL_ALL_DENY_MINTS", "")).split(",") if m.strip()}

def rpc(method, params):
    r = requests.post(RPC_HTTP, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=30)
    r.raise_for_status()
    return r.json()

def get_owner():
    secret = json.load(open(KEYPAIR_PATH, "r", encoding="utf-8"))
    kp = Keypair.from_bytes(bytes(secret))
    return kp, str(kp.pubkey())

def list_token_accounts(owner: str):
    j = rpc("getTokenAccountsByOwner", [owner, {"programId":"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding":"jsonParsed"}])
    out = []
    for v in (j.get("result", {}) or {}).get("value", []) or []:
        try:
            info = v["account"]["data"]["parsed"]["info"]
            mint = info["mint"]
            ta = info["tokenAmount"]
            ui = float(ta.get("uiAmount") or 0.0)
            amt = int(ta.get("amount") or "0")
            dec = int(ta.get("decimals") or 0)
            if ui <= MIN_UI or amt <= 0:
                continue
            out.append((mint, amt, ui, dec))
        except Exception:
            continue
    return out

def jup_quote(input_mint: str, amount_raw: int):
    url = f"{JUP_BASE}/swap/v1/quote"
    params = {
        "inputMint": input_mint,
        "outputMint": SOL_MINT,
        "amount": str(int(amount_raw)),
        "slippageBps": str(int(SLIPPAGE_BPS)),
    }
    r = requests.get(url, params=params, timeout=35)
    if r.status_code != 200:
        return None, f"quote_http={r.status_code} {r.text[:200]}"
    return r.json(), None

def jup_swap(quote, owner_pubkey: str):
    url = f"{JUP_BASE}/swap/v1/swap"
    body = {"quoteResponse": quote, "userPublicKey": owner_pubkey, "wrapAndUnwrapSol": True}
    r = requests.post(url, json=body, timeout=35)
    if r.status_code != 200:
        return None, f"swap_http={r.status_code} {r.text[:200]}"
    j = r.json()
    txb64 = j.get("swapTransaction")
    if not txb64:
        return None, "swap_no_tx"
    return txb64, None

def send_signed_b64(txb64: str, kp: Keypair):
    tx_bytes = base64.b64decode(txb64)
    vtx = VersionedTransaction.from_bytes(tx_bytes)
    vtx = VersionedTransaction(vtx.message, [kp])
    raw = bytes(vtx)
    raw64 = base64.b64encode(raw).decode("utf-8")
    j = rpc("sendTransaction", [raw64, {"encoding":"base64", "skipPreflight": False, "preflightCommitment":"processed"}])
    if "error" in j:
        raise RuntimeError(f"sendTransaction error={j['error']}")
    return j.get("result")

def main():
    kp, owner = get_owner()
    print("wallet=", owner)
    print("rpc   =", RPC_HTTP)
    print("jup   =", JUP_BASE)
    print("slip  =", SLIPPAGE_BPS, "bps")
    print("dry   =", DRY_RUN)
    if DENY:
        print("deny  =", ",".join(sorted(DENY)))

    toks = list_token_accounts(owner)
    toks = [t for t in toks if t[0] != SOL_MINT and t[0] not in DENY]
    toks.sort(key=lambda x: x[2], reverse=True)  # tri par uiAmount
    print("tokens_to_sell=", len(toks))

    for mint, amt_raw, ui, dec in toks:
        print(f"\n=== SELL mint={mint} ui={ui} raw={amt_raw} dec={dec} ===")
        quote, err = jup_quote(mint, amt_raw)
        if err:
            print("❌", err); continue
        out_amt = quote.get("outAmount")
        route = ""
        try:
            rp = quote.get("routePlan") or []
            if rp:
                route = " > ".join([ (x.get("swapInfo") or {}).get("label","?") for x in rp[:5] ])
        except Exception:
            route = ""
        print("route=", route[:200])
        print("outAmount(raw SOL)=", out_amt)

        txb64, err = jup_swap(quote, owner)
        if err:
            print("❌", err); continue

        if DRY_RUN:
            print("🧪 DRY_RUN=1 -> not sending"); continue

        try:
            sig = send_signed_b64(txb64, kp)
            print("✅ sent txsig=", sig)
        except Exception as e:
            print("❌ send exception:", e)

        time.sleep(1.2)

if __name__ == "__main__":
    main()
