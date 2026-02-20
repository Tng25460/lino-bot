#!/usr/bin/env python3
import argparse, json, os, time
import urllib.request, urllib.error

SOL = "So11111111111111111111111111111111111111112"

def _read_jsonl(path: str):
    out=[]
    with open(path, "r", encoding="utf-8", errors="replace") as f:
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
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def _get_mint(row):
    for k in ("mint","output_mint","out_mint","token_mint","address"):
        v=row.get(k)
        if isinstance(v,str) and len(v) > 20:
            return v
    return None

def _get_score(row):
    for k in ("score","brain_score","final_score"):
        v=row.get(k)
        if isinstance(v,(int,float)):
            return float(v)
        if isinstance(v,str):
            try: return float(v)
            except: pass
    return None

def _get_pnl_pct(row):
    for k in ("pnl_pct","pnlPct","pnl_percent","pnlPercent","recent_pnl_pct","pnl_pct_recent"):
        v=row.get(k)
        if isinstance(v,(int,float)):
            return float(v)
        if isinstance(v,str):
            try: return float(v)
            except: pass
    return None

def _jup_quote(base_url: str, out_mint: str, amount: int, slip_bps: int):
    url = (
        base_url.rstrip("/")
        + "/swap/v1/quote"
        + f"?inputMint={SOL}&outputMint={out_mint}"
        + f"&amount={int(amount)}"
        + f"&slippageBps={int(slip_bps)}"
    )
    req = urllib.request.Request(url, headers={"accept":"application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", dest="out", required=True)
    p.add_argument("--jup", default=os.getenv("JUP_BASE_URL","https://lite-api.jup.ag"))
    p.add_argument("--amount", type=int, default=int(os.getenv("FILTER_TRADABLE_AMOUNT","10000000")))
    p.add_argument("--slip-bps", type=int, default=int(os.getenv("FILTER_TRADABLE_SLIP_BPS","120")))
    p.add_argument("--retries", type=int, default=int(os.getenv("FILTER_TRADABLE_RETRIES","6")))
    p.add_argument("--min-interval-sec", type=float, default=float(os.getenv("FILTER_TRADABLE_MIN_INTERVAL_SEC","0.6")))
    p.add_argument("--on429-keep", type=int, default=int(os.getenv("FILTER_TRADABLE_ON429_KEEP","1")))
    p.add_argument("--min-score", type=float, default=float(os.getenv("BRAIN_SCORE_MIN","0.03")))
    p.add_argument("--top-n", type=int, default=int(os.getenv("BRAIN_TOPN","60")))
    p.add_argument("--max-neg-pnl-pct", type=float, default=float(os.getenv("FILTER_TRADABLE_MAX_NEG_PNL_PCT","5")))
    args=p.parse_args()

    rows=_read_jsonl(args.inp)
    print(f"[filter_ready_tradable] rows_in={len(rows)} file={args.inp}", flush=True)

    rows2=[]
    for r in rows:
        m=_get_mint(r)
        if m:
            r["_mint"]=m
            rows2.append(r)
    print(f"[filter_ready_tradable] rows_with_mint={len(rows2)}", flush=True)

    # anti-dump
    if args.max_neg_pnl_pct and float(args.max_neg_pnl_pct) > 0:
        thr = -abs(float(args.max_neg_pnl_pct))
        kept=[]
        for r in rows2:
            pnl=_get_pnl_pct(r)
            if pnl is not None and pnl <= thr:
                continue
            kept.append(r)
        rows2=kept

    # score sort + top-n
    rows3=[]
    for r in rows2:
        sc=_get_score(r)
        r["_score"]=sc if sc is not None else -1e9
        rows3.append(r)
    rows3.sort(key=lambda x: x.get("_score",-1e9), reverse=True)

    top = rows3[: max(0,int(args.top_n))]
    if top:
        print(f"[filter_ready_tradable] after_score top={len(top)} top1_mint={top[0]['_mint']} top1_score={top[0]['_score']:.4f}", flush=True)
    else:
        print("[filter_ready_tradable] after_score top=0", flush=True)

    kept=[]
    bad=0
    soft429=0
    last_t=0.0

    for i,r in enumerate(top, start=1):
        m=r["_mint"]

        # throttle
        now=time.time()
        dt=now-last_t
        if dt < args.min_interval_sec:
            time.sleep(args.min_interval_sec - dt)

        ok=False
        for k in range(args.retries):
            try:
                _ = _jup_quote(args.jup, m, args.amount, args.slip_bps)
                ok=True
                break
            except urllib.error.HTTPError as e:
                code=getattr(e,"code",None)
                if code == 429:
                    soft429 += 1
                    if args.on429_keep == 1:
                        ok=True
                        break
                    time.sleep(0.8 + 0.4*k)
                    continue
                bad += 1
                ok=False
                break
            except Exception:
                bad += 1
                ok=False
                break

        last_t=time.time()
        if ok:
            r.pop("_mint", None)
            r.pop("_score", None)
            kept.append(r)

        if i % 10 == 0:
            print(f"[dbg] progress {i}/{len(top)} kept={len(kept)} bad={bad} soft429={soft429}", flush=True)

    _write_jsonl(args.out, kept)
    print(f"DONE kept={len(kept)} bad={bad} soft429={soft429} unauth=0 OUT={args.out}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
