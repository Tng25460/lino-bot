#!/usr/bin/env python3
import os, json

INP=os.getenv("INP","state/ready_final.jsonl")
OUT=os.getenv("OUT","state/ready_final.nobase.jsonl")

EX=set([
  "So11111111111111111111111111111111111111112",  # SOL
  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
  "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
])

tot=0; kept=0; bad=0; dropped=0
with open(INP,"r",encoding="utf-8") as f, open(OUT,"w",encoding="utf-8") as g:
  for line in f:
    line=line.strip()
    if not line:
      continue
    tot += 1
    try:
      j=json.loads(line)
    except Exception:
      bad += 1
      continue
    m=(j.get("mint") or "").strip()
    if m in EX:
      dropped += 1
      continue
    kept += 1
    g.write(json.dumps(j, separators=(",",":"))+"\n")

print(f"[OK] exclude base/stables: in={INP} total={tot} bad={bad} dropped={dropped} kept={kept} out={OUT}")
