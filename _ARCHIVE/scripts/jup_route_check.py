import os, json, time, argparse, urllib.parse, urllib.request
from urllib.error import HTTPError

def jup_headers():
    h = {"accept": "application/json"}
    k = os.environ.get("JUP_API_KEY") or os.environ.get("JUP_API_KEY_HEADER")
    if k:
        h["x-api-key"] = k
    return h

def jup_get(base_url: str, path: str, params: dict, timeout_s: int = 12):
    q = urllib.parse.urlencode(params, doseq=True)
    url = base_url.rstrip("/") + path + ("?" + q if q else "")
    req = urllib.request.Request(url, headers=jup_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            j = json.loads(body)
        except Exception:
            j = {"http_error": e.code, "body": body[:500]}
        j["_http_status"] = e.code
        return j

def iter_jsonl(path: str):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            yield json.loads(line)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out_ok", required=True)
    ap.add_argument("--reject", dest="out_bad", default=None)
    ap.add_argument("--base", dest="base", default=os.environ.get("JUP_BASE_URL","https://api.jup.ag"))
    ap.add_argument("--dexes", dest="dexes", default=os.environ.get("ALLOWED_DEXES","raydium,meteora"))
    ap.add_argument("--amount", dest="amount", type=int, default=int(os.environ.get("JUP_TEST_AMOUNT_LAMPORTS","1000000")))
    ap.add_argument("--slip", dest="slip", type=int, default=int(os.environ.get("JUP_SLIPPAGE_BPS","250")))
    ap.add_argument("--sleep", dest="sleep", type=float, default=float(os.environ.get("JUP_ROUTE_SLEEP","0.08")))
    ap.add_argument("--max", dest="maxn", type=int, default=int(os.environ.get("JUP_ROUTE_MAX","200")))
    args = ap.parse_args()

    in_mint = os.environ.get("INPUT_MINT","So11111111111111111111111111111111111111112")
    dexes = [d.strip() for d in args.dexes.split(",") if d.strip()]

    kept = total = 0
    bad_f = open(args.out_bad, "w", encoding="utf-8") if args.out_bad else None
    try:
        with open(args.out_ok, "w", encoding="utf-8") as ok_f:
            for row in iter_jsonl(args.inp):
                if total >= args.maxn: break
                total += 1

                out_mint = row.get("mint") or row.get("outputMint") or row.get("token_mint")
                if not out_mint:
                    row["jup_route_ok"] = False
                    row["jup_route_errcode"] = "missing_output_mint"
                    if bad_f: bad_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    continue

                data = jup_get(
                    args.base,
                    "/swap/v1/quote",
                    {
                        "inputMint": in_mint,
                        "outputMint": out_mint,
                        "amount": str(args.amount),
                        "slippageBps": str(args.slip),
                        "dexes": dexes,
                    },
                )

                ok = isinstance(data, dict) and bool(data.get("routePlan"))
                errcode = None
                if not ok:
                    errcode = data.get("errorCode") or data.get("code") or data.get("error") or data.get("message") or "no_route"
                    if isinstance(errcode, dict): errcode = json.dumps(errcode)[:200]

                row["jup_route_ok"] = ok
                row["jup_route_dexes"] = dexes
                row["jup_route_errcode"] = None if ok else str(errcode)
                row["jup_route_http"] = data.get("_http_status") if isinstance(data, dict) else None

                if ok:
                    kept += 1
                    ok_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                else:
                    if bad_f: bad_f.write(json.dumps(row, ensure_ascii=False) + "\n")

                if total % 20 == 0:
                    print(f"[route_check] progress total={total} kept={kept}")

                time.sleep(args.sleep)
    finally:
        if bad_f: bad_f.close()

    print(f"route_check: in={args.inp} out={args.out_ok} reject={args.out_bad} total={total} kept={kept} base={args.base} dexes={dexes}")

if __name__ == "__main__":
    main()
