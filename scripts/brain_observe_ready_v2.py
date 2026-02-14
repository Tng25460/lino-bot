import os, json, time, sqlite3, requests
from pathlib import Path

DB  = os.getenv("BRAIN_DB", "state/brain.sqlite")
INP = os.getenv("READY_FILE", "state/ready_tradable.jsonl")
RPC = os.getenv("RPC_HTTP", "https://api.mainnet-beta.solana.com")
JUP = os.getenv("JUP_BASE_URL", "https://lite-api.jup.ag").rstrip("/")
SOL = "So11111111111111111111111111111111111111112"

MAX_MINTS = int(os.getenv("BRAIN_OBS_MAX_MINTS", "30"))
SLEEP_S  = float(os.getenv("BRAIN_OBS_SLEEP_S", "3.5"))
SLIP_BPS = int(os.getenv("BRAIN_OBS_SLIPPAGE_BPS", os.getenv("SLIPPAGE_BPS", "120")))

TIMEOUT = float(os.getenv("BRAIN_HTTP_TIMEOUT", "25"))

def rpc(method, params):
    r = requests.post(RPC, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=TIMEOUT)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j["result"]

_dec_cache = {}
def decimals(mint):
    if mint in _dec_cache:
        return _dec_cache[mint]
    d = int(rpc("getTokenSupply", [mint])["value"]["decimals"])
    _dec_cache[mint] = d
    return d

def read_ready(path):
    out = []
    p = Path(path)
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            mint = j.get("mint") or j.get("output_mint") or j.get("token") or j.get("address")
            if not mint:
                continue
            out.append(j)
    return out

def jup_quote_token_to_sol(mint, amount_base_str):
    url = f"{JUP}/swap/v1/quote"
    params = {
        "inputMint": mint,
        "outputMint": SOL,
        "amount": str(amount_base_str),
        "slippageBps": str(SLIP_BPS),
    }
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code == 429:
        return None, "429"
    if r.status_code != 200:
        return None, f"http={r.status_code}"
    try:
        q = r.json()
    except Exception:
        return None, "bad_json"
    return q, None

def db_cols(con, table):
    cur = con.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]

def insert_dynamic(con, table, row_dict):
    cols = set(db_cols(con, table))
    keep = {k: v for k, v in row_dict.items() if k in cols}
    if not keep:
        return 0
    keys = sorted(keep.keys())
    qs = ",".join(["?"] * len(keys))
    sql = f"INSERT INTO {table} ({','.join(keys)}) VALUES ({qs})"
    con.execute(sql, [keep[k] for k in keys])
    return 1

def fnum(x, default=0.0):
    try:
        if x is None:
            return float(default)
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "":
            return float(default)
        return float(s)
    except Exception:
        return float(default)

def main():
    rows = read_ready(INP)
    rows = rows[:MAX_MINTS]
    print(f"[brain_observe_ready_v2] mints={len(rows)}/{MAX_MINTS} INP={INP} DB={DB} JUP={JUP} slip_bps={SLIP_BPS}")

    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    cols = db_cols(con, "token_observations")
    print(f"[brain_observe_ready_v2] token_observations cols={cols}")

    inserted = 0
    for i, j in enumerate(rows, 1):
        mint = j.get("mint") or j.get("output_mint") or j.get("token") or j.get("address")
        ts = int(time.time())

        # pull metrics from ready line if present
        row = {
            "ts": ts,
            "mint": mint,
            "source": j.get("src") or j.get("source") or "ready",
            "flags": j.get("flags") or "",
            "liq_usd": fnum(j.get("liq_usd") or j.get("liquidity_usd") or j.get("liquidity")),
            "vol_5m": fnum(j.get("vol_5m") or j.get("volume_5m")),
            "vol_1h": fnum(j.get("vol_1h") or j.get("volume_1h")),
            "txns_5m": fnum(j.get("txns_5m") or j.get("tx_5m") or j.get("trades_5m")),
            "txns_1h": fnum(j.get("txns_1h") or j.get("tx_1h") or j.get("trades_1h")),
            "holders": int(fnum(j.get("holders"), 0)),
            "top10_pct": fnum(j.get("top10_pct") or j.get("top10"), 0.0),
        }

        try:
            dec = decimals(mint)
            amt_base = 10 ** int(dec)  # 1 token in base units
            q, err = jup_quote_token_to_sol(mint, amt_base)
            if err == "429":
                print(f"[{i}/{len(rows)}] mint={mint} skip quote_err=429")
                time.sleep(SLEEP_S)
                continue
            if err is not None:
                print(f"[{i}/{len(rows)}] mint={mint} skip quote_err={err}")
                time.sleep(SLEEP_S)
                continue

            out_amount = int(q.get("outAmount", "0"))
            price_sol_per_token = (out_amount / 1e9)  # since input was 1 token
            row["price"] = float(price_sol_per_token)

            # extra signals
            imp = fnum(q.get("priceImpactPct"), 0.0)
            rplan = q.get("routePlan") or []
            rlen = int(len(rplan)) if isinstance(rplan, list) else 0
            row["price_impact_pct"] = float(imp)
            row["route_len"] = int(rlen)

            inserted += insert_dynamic(con, "token_observations", row)
            con.commit()
            print(f"[{i}/{len(rows)}] mint={mint} price_sol_per_token={row['price']:.10g} imp={imp:.6g} rlen={rlen} inserted={inserted}")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[{i}/{len(rows)}] mint={mint} err={type(e).__name__}: {e}")
        time.sleep(SLEEP_S)

    con.close()
    print(f"[brain_observe_ready_v2] DONE inserted={inserted}")

if __name__ == "__main__":
    main()
