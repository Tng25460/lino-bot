import os, sys, time, json, subprocess, requests

RPC = os.getenv("RPC_HTTP_READ", "https://api.mainnet-beta.solana.com").split(",")[0].strip()
OWNER = subprocess.check_output(["solana","address","-k","keypair.json"], text=True).strip()

MIN_UI = float(os.getenv("SELL_WALLET_MIN_UI", "0"))
SLEEP_S = float(os.getenv("SELL_WALLET_SLEEP_S", "2.5"))
TIMEOUT_S = int(os.getenv("SELL_WALLET_TIMEOUT_S", "70"))

PY_EXE = os.getenv("PY_EXE") or sys.executable

def get_nonzero_accounts():
    payload = {
      "jsonrpc":"2.0","id":1,"method":"getTokenAccountsByOwner",
      "params":[OWNER, {"programId":"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding":"jsonParsed"}]
    }
    r = requests.post(RPC, json=payload, timeout=25)
    r.raise_for_status()
    vals = r.json()["result"]["value"]

    rows=[]
    for it in vals:
        info = it["account"]["data"]["parsed"]["info"]
        mint = info["mint"]
        tok = info["tokenAmount"]
        ui = float(tok.get("uiAmount") or 0.0)
        if ui > MIN_UI:
            rows.append((mint, ui))
    # plus gros d'abord
    rows.sort(key=lambda x: -x[1])
    return rows

def run_sell(mint, ui):
    cmd = [PY_EXE, "-u", "src/sell_exec_wrap.py", "--mint", mint, "--ui", str(ui), "--reason", "wallet_liquidation"]
    print("🧾", " ".join(cmd), flush=True)
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        print("⏳ TIMEOUT", mint, flush=True)
        return "__TIMEOUT__", 124, ""

    out = (p.stdout or "") + "\n" + (p.stderr or "")
    out = out.strip()

    # heuristiques
    if "__ROUTE_FAIL__" in out or "ROUTE_FAIL" in out:
        return "__ROUTE_FAIL__", p.returncode, out[-800:]
    if "JUP_INSUFFICIENT_FUNDS" in out or "insufficient funds" in out.lower():
        return "__INSUFFICIENT__", p.returncode, out[-800:]

    # cherche txsig
    txsig = None
    for line in (p.stdout or "").splitlines()[::-1]:
        if "txsig" in line:
            txsig = line.split("txsig=")[-1].strip()
            break
    return txsig or "__UNKNOWN__", p.returncode, out[-800:]

def main():
    rows = get_nonzero_accounts()
    print("[RPC]", RPC)
    print("[owner]", OWNER)
    print("[nonzero > MIN_UI]", len(rows), "MIN_UI=", MIN_UI)
    for i,(mint,ui) in enumerate(rows, 1):
        print(f"\n[{i}/{len(rows)}] mint={mint} ui={ui}", flush=True)
        txsig, rc, tail = run_sell(mint, ui)
        print(f"➡️ result mint={mint} rc={rc} txsig={txsig}", flush=True)
        if tail:
            print("---- tail ----")
            print(tail)
            print("--------------")
        time.sleep(SLEEP_S)

if __name__ == "__main__":
    main()
