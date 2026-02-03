#!/usr/bin/env python3
import os, json

INP=os.getenv("INP","state/ready_final.nobase.jsonl")
OUT=os.getenv("OUT","state/ready_final.capped.jsonl")
MAX_MCAP=float(os.getenv("MAX_MCAP","5000000"))   # 5M default
MAX_FDV=float(os.getenv("MAX_FDV","10000000"))    # 10M default

tot=kept=dropped=bad=0
with open(INP,"r",encoding="utf-8") as f, open(OUT,"w",encoding="utf-8") as g:
  for line in f:
    line=line.strip()
    if not line: continue
    tot += 1
    try: j=json.loads(line)
    except: bad += 1; continue
    mcap=float(j.get("market_cap") or 0.0)
    fdv=float(j.get("fdv") or 0.0)
    if (mcap and mcap > MAX_MCAP) or (fdv and fdv > MAX_FDV):
      dropped += 1
      continue
    kept += 1
    g.write(json.dumps(j,separators=(",",":"))+"\n")

print(f"[OK] cap filter: in={INP} total={tot} bad={bad} dropped={dropped} kept={kept} out={OUT}")
