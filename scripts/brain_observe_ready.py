import os, json, time, sqlite3, requests
import sys

DB  = os.getenv("BRAIN_DB", "state/brain.sqlite")
INP = os.getenv("READY_FILE", "state/ready_tradable.jsonl")
RPC = os.getenv("RPC_HTTP", "https://api.mainnet-beta.solana.com")
JUP = os.getenv("JUP_BASE_URL", "https://lite-api.jup.ag").rstrip("/")
SOL = "So11111111111111111111111111111111111111112"
MAX_MINTS = int(os.getenv("BRAIN_OBS_MAX_MINTS", "20"))
SLEEP_S  = float(os.getenv("BRAIN_OBS_SLEEP_S", "2.5"))

def rpc(method, params):
    r = requests.post(RPC, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=25)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j["result"]

_dec_cache = {}
def decimals(mint):
    if mint in _dec_cache: return _dec_cache[mint]
    d = int(rpc("getTokenSupply", [mint])["value"]["decimals"])
    _dec_cache[mint] = d
    return d

def quote_token_to_sol(mint, ui_amt, dec):
    amt = int(max(1, round(ui_amt * (10**dec))))
    url = f"{JUP}/swap/v1/quote"
    params = {"inputMint": mint, "outputMint": SOL, "amount": str(amt), "slippageBps": "120"}
    for k in range(4):
        r = requests.get(url, params=params, timeout=25)
        if r.status_code == 429:
            time.sleep(5.0 + k*5.0); continue
        if r.status_code != 200:
            return None, f"http={r.status_code}"
        j = r.json()
        out = int(j.get("outAmount","0") or 0)
        if out <= 0:
            return None, "out=0"
        sol_out = out / 1e9
        return (sol_out / ui_amt), None
    return None, "429"

def table_cols(con, table):
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}

def main():
    if not os.path.exists(INP):
        print(f"[brain_observe_ready] missing INP={INP}")
        return

    mints=[]
    with open(INP, "r", encoding="utf-8") as f:
        for line in f:
            if len(mints) >= MAX_MINTS: break
            line=line.strip()
            if not line: continue
            try:
                o=json.loads(line)
                m=(o.get("mint") or "").strip()
                if m and m not in mints:
                    mints.append(m)
            except: pass

    print(f"[brain_observe_ready] mints={len(mints)}/{MAX_MINTS} INP={INP} DB={DB} JUP={JUP}")

    con = sqlite3.connect(DB)
    cols = table_cols(con, "token_observations")
    print(f"[brain_observe_ready] token_observations cols={sorted(list(cols))}")

    now = int(time.time())
    inserted=0
    for i, mint in enumerate(mints, 1):
        try:
            dec = decimals(mint)
            px, err = quote_token_to_sol(mint, 1.0, dec)
            if px is None:
                print(f"[{i}/{len(mints)}] mint={mint} skip quote_err={err}")
                time.sleep(SLEEP_S)
                continue

            row={}
            if "mint" in cols: row["mint"]=mint
            if "ts" in cols: row["ts"]=now
            if "timestamp" in cols: row["timestamp"]=now
            if "price" in cols: row["price"]=px
            if "price_sol" in cols: row["price_sol"]=px
            if "source" in cols: row["source"]="jup_quote"
            if "created_at" in cols: row["created_at"]=now

            if not row:
                print("[brain_observe_ready] no compatible columns found")
                return

            keys=list(row.keys())
            q=",".join(["?"]*len(keys))
            con.execute(f"INSERT INTO token_observations ({','.join(keys)}) VALUES ({q})", [row[k] for k in keys])
            con.commit()
            inserted += 1
            print(f"[{i}/{len(mints)}] mint={mint} price_sol_per_token={px:.12g} inserted={inserted}")
        except Exception as e:
            print(f"[{i}/{len(mints)}] mint={mint} err={e}")
        time.sleep(SLEEP_S)

    con.close()
    print(f"[brain_observe_ready] DONE inserted={inserted}")

if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        sys.exit(0)
