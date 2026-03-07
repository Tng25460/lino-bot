#!/usr/bin/env python3
import argparse, json, os, time
import urllib.request, urllib.error

SOL = "So11111111111111111111111111111111111111112"

MINT_KEYS  = ("mint","output_mint","outputMint","token","address")
SCORE_KEYS = ("score","brain_score","final_score","score_v4","scoreV4","score_total")

def _read_jsonl(path: str):
    out=[]
    with open(path,"r",encoding="utf-8",errors="replace") as f:
        for ln in f:
            ln=ln.strip()
            if not ln: 
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
    return out

def _write_jsonl(path: str, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path,"w",encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def _mint(r):
    for k in MINT_KEYS:
        v = r.get(k)
        if isinstance(v,str) and v.strip():
            return v.strip()
    return ""

def _score(r):
    for k in SCORE_KEYS:
        if k in r:
            try:
                return float(r.get(k))
            except Exception:
                pass
    return float("-inf")

def _sleep_throttle(last_ts, min_interval):
    if min_interval <= 0:
        return time.time()
    now=time.time()
    dt=now-last_ts
    if dt < min_interval:
        time.sleep(min_interval-dt)
        return time.time()
    return now

def _quote(jup_base: str, mint: str, amount: int, slip_bps: int, timeout=20):
    url=(f"{jup_base.rstrip('/')}/swap/v1/quote"
         f"?inputMint={SOL}&outputMint={mint}&amount={int(amount)}&slippageBps={int(slip_bps)}")
    req=urllib.request.Request(url, headers={"accept":"application/json"})
    raw=urllib.request.urlopen(req, timeout=timeout).read()
    return json.loads(raw)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--jup-base", default=os.getenv("JUP_BASE_URL","https://lite-api.jup.ag"))
    ap.add_argument("--amount", type=int, default=int(float(os.getenv("FILTER_TRADABLE_AMOUNT","10000000"))))
    ap.add_argument("--slip-bps", type=int, default=int(float(os.getenv("SLIPPAGE_BPS", os.getenv("FILTER_TRADABLE_SLIP_BPS","120")))))
    ap.add_argument("--retries", type=int, default=int(float(os.getenv("FILTER_TRADABLE_RETRIES","6"))))
    ap.add_argument("--on429-keep", type=int, default=int(float(os.getenv("FILTER_TRADABLE_ON429_KEEP","1"))))
    ap.add_argument("--min-score", type=float, default=float(os.getenv("BRAIN_SCORE_MIN", os.getenv("FILTER_TRADABLE_MIN_SCORE","-1"))))
    ap.add_argument("--top-n", type=int, default=int(float(os.getenv("BRAIN_TOPN", os.getenv("FILTER_TRADABLE_TOPN","60")))))
    ap.add_argument("--min-interval-sec", type=float, default=float(os.getenv("FILTER_TRADABLE_MIN_INTERVAL_SEC","0.25")))
    ap.add_argument("--debug", type=int, default=int(float(os.getenv("FILTER_TRADABLE_DEBUG","1"))))
    args=ap.parse_args()

    rows=_read_jsonl(args.inp)
    if args.debug:
        print(f"[filter_ready_tradable] rows_in={len(rows)} file={args.inp}")

    # drop rows sans mint
    rows=[r for r in rows if _mint(r)]
    if args.debug:
        print(f"[filter_ready_tradable] rows_with_mint={len(rows)}")

    # score filter
    if args.min_score is not None and args.min_score > -1:
        rows=[r for r in rows if _score(r) >= args.min_score]
    rows.sort(key=_score, reverse=True)

    if args.top_n and args.top_n > 0:
        rows=rows[:args.top_n]

    if args.debug:
        if rows:
            r0=rows[0]
            print(f"[filter_ready_tradable] after_score top={len(rows)} top1_mint={_mint(r0)} top1_score={_score(r0):.4f}")
        else:
            print(f"[filter_ready_tradable] after_score top=0 (min_score={args.min_score} top_n={args.top_n})")

    kept=[]; bad=0; soft429=0; unauth=0; last_ts=0.0

    for r in rows:
        mint=_mint(r)
        ok=False
        last_err=None
        for attempt in range(max(1,args.retries)):
            last_ts=_sleep_throttle(last_ts, args.min_interval_sec)
            try:
                q=_quote(args.jup_base, mint, args.amount, args.slip_bps)
                out_amt=int(q.get("outAmount") or 0)
                if out_amt>0:
                    ok=True; break
                last_err="outAmount<=0"
            except urllib.error.HTTPError as e:
                code=getattr(e,"code",None)
                if code in (401,403):
                    unauth += 1; last_err=f"http={code}"; break
                if code==429:
                    soft429 += 1; last_err="http=429"
                    time.sleep(0.25 + 0.35*attempt)
                    continue
                last_err=f"http={code}"
                break
            except Exception as e:
                last_err=f"{type(e).__name__}:{e}"
                time.sleep(0.15)
                continue

        if ok:
            kept.append(r)
        else:
            bad += 1
            if args.on429_keep==1 and last_err=="http=429":
                kept.append(r)

    _write_jsonl(args.out, kept)
    print(f"DONE kept={len(kept)} bad={bad} soft429={soft429} unauth={unauth} OUT={args.out}")

if __name__=="__main__":
    raise SystemExit(main())
