import os

READY_TRADABLE_IN = os.getenv('READY_TRADABLE_IN', 'state/ready_pump_early.jsonl')
READY_TRADABLE_OUT = os.getenv('READY_TRADABLE_OUT', 'state/ready_tradable.jsonl')
#!/usr/bin/env python3
import json, os, time
import requests
INP = os.getenv('READY_TRADABLE_IN', 'state/ready_pump_early.jsonl')
OUT = os.getenv('READY_TRADABLE_OUT', 'state/ready_tradable.jsonl')
print(f"[filter_ready_tradable] INP={INP} OUT={OUT}")

JUP = os.getenv("JUP_BASE_URL", "https://lite-api.jup.ag")
AMOUNT = str(int(float(os.getenv("BUY_AMOUNT_SOL","0.003")) * 1e9))
SLIPPAGE = os.getenv("SLIPPAGE_BPS", "120")

def ok_quote(mint: str) -> tuple[bool,str]:
    params = {
        "inputMint":"So11111111111111111111111111111111111111112",
        "outputMint": mint,
        "amount": AMOUNT,
        "slippageBps": SLIPPAGE,
    }
    try:
        r = requests.get(f"{JUP}/swap/v1/quote", params=params, timeout=12)
        if r.status_code == 200:
            return True, ""
        txt = (r.text or "")[:200]
        return False, f"http={r.status_code} body={txt}"
    except Exception as e:
        return False, f"exc={e}"

rows = []
with open(INP,"r",encoding="utf-8") as f:
    for ln in f:
        ln = ln.strip()
        if not ln: 
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            pass

kept = 0
bad = 0
with open(OUT,"w",encoding="utf-8") as w:
    for i, o in enumerate(rows, 1):
        mint = (o.get("mint") or o.get("outputMint") or o.get("address") or "").strip()
        if not mint:
            bad += 1
            continue
        ok, why = ok_quote(mint)
        if ok:
            w.write(json.dumps(o, ensure_ascii=False) + "\n")
            kept += 1
        else:
            bad += 1
        if i % 10 == 0:
            print(f"[{i}/{len(rows)}] kept={kept} bad={bad}")
        time.sleep(0.12)

print("DONE kept=", kept, "bad=", bad, "OUT=", OUT)
