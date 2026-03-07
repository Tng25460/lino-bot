import os, json, time, argparse, subprocess, urllib.parse

def iter_jsonl(path: str):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line:
                continue
            yield json.loads(line)

def curl_get_json(url: str, headers: dict, timeout_s: int):
    cmd = ["curl", "-sS", "--max-time", str(timeout_s)]
    for k,v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd += [url]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return {"_curl_error": p.stderr.strip()[:400], "_curl_rc": p.returncode}
    try:
        return json.loads(p.stdout)
    except Exception:
        return {"_json_error": "failed_to_parse", "_body": p.stdout[:400]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out_ok", required=True)
    ap.add_argument("--reject", dest="out_bad", default=None)
    ap.add_argument("--base", dest="base", default=os.environ.get("JUP_BASE_URL","https://api.jup.ag"))
    ap.add_argument("--dexes", dest="dexes", default=os.environ.get("ALLOWED_DEXES",""))
    ap.add_argument("--amount", dest="amount", type=int, default=int(os.environ.get("JUP_TEST_AMOUNT_LAMPORTS","1000000")))
    ap.add_argument("--slip", dest="slip", type=int, default=int(os.environ.get("JUP_SLIPPAGE_BPS","800")))
    ap.add_argument("--sleep", dest="sleep", type=float, default=float(os.environ.get("JUP_ROUTE_SLEEP","0.06")))
    ap.add_argument("--max", dest="maxn", type=int, default=int(os.environ.get("JUP_ROUTE_MAX","200")))
    ap.add_argument("--timeout", dest="timeout", type=int, default=int(os.environ.get("JUP_CURL_TIMEOUT","12")))
    args = ap.parse_args()

    in_mint = os.environ.get("INPUT_MINT","So11111111111111111111111111111111111111112")
    dexes = [d.strip() for d in args.dexes.split(",") if d.strip()]

    headers = {"accept": "application/json"}
    k = os.environ.get("JUP_API_KEY") or os.environ.get("JUP_API_KEY_HEADER")
    if k:
        headers["x-api-key"] = k

    kept = total = 0
    bad_f = open(args.out_bad, "w", encoding="utf-8") if args.out_bad else None
    try:
        with open(args.out_ok, "w", encoding="utf-8") as ok_f:
            for row in iter_jsonl(args.inp):
                if total >= args.maxn:
                    break
                total += 1

                out_mint = row.get("mint") or row.get("outputMint") or row.get("token_mint")
                if not out_mint:
                    row["jup_route_ok"] = False
                    row["jup_route_errcode"] = "missing_output_mint"
                    if bad_f: bad_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    continue

                params = {
                    "inputMint": in_mint,
                    "outputMint": out_mint,
                    "amount": str(args.amount),
                    "slippageBps": str(args.slip),
                }
                if dexes:
                    # IMPORTANT: keep labels as-is (case + "+")
                    params["dexes"] = dexes

                q = urllib.parse.urlencode(params, doseq=True)
                url = args.base.rstrip("/") + "/swap/v1/quote" + "?" + q

                data = curl_get_json(url, headers=headers, timeout_s=args.timeout)

                ok = isinstance(data, dict) and bool(data.get("routePlan"))
                errcode = None
                if not ok:
                    errcode = data.get("errorCode") or data.get("code") or data.get("error") or data.get("message")
                    if not errcode and "_curl_error" in data:
                        errcode = "CURL_ERROR"
                    if not errcode and "_json_error" in data:
                        errcode = "JSON_PARSE_ERROR"
                    if errcode is None:
                        errcode = "no_route"

                row["jup_route_ok"] = ok
                row["jup_route_dexes"] = dexes
                row["jup_route_errcode"] = None if ok else str(errcode)
                row["jup_route_dbg"] = None if ok else data

                if ok:
                    kept += 1
                    ok_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                else:
                    if bad_f: bad_f.write(json.dumps(row, ensure_ascii=False) + "\n")

                if total % 20 == 0:
                    print(f"[route_check_curl] progress total={total} kept={kept}")

                time.sleep(args.sleep)
    finally:
        if bad_f: bad_f.close()

    print(f"route_check_curl: in={args.inp} out={args.out_ok} reject={args.out_bad} total={total} kept={kept} base={args.base} dexes={dexes}")

if __name__ == "__main__":
    main()
