#!/usr/bin/env python3
import os, json

INP=os.getenv("READY_IN","state/ready_wallet_scored.jsonl")
OUT=os.getenv("READY_OUT","state/ready_wallet_scored.filtered.jsonl")
DROP_FILE=os.getenv("DROP_MINTS_FILE","state/drop_mints.txt")

drop=set()
try:
    with open(DROP_FILE,"r",encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line or line.startswith("#"): 
                continue
            drop.add(line)
except FileNotFoundError:
    pass

kept=0
seen=0
with open(INP,"r",encoding="utf-8") as f, open(OUT,"w",encoding="utf-8") as g:
    for line in f:
        line=line.strip()
        if not line: 
            continue
        seen += 1
        try:
            o=json.loads(line)
        except Exception:
            continue
        mint=o.get("mint")
        if not mint:
            continue
        if mint in drop:
            continue
        g.write(json.dumps(o,separators=(",",":"))+"\n")
        kept += 1

print(f"[OK] filtered ready: in={INP} out={OUT} seen={seen} kept={kept} dropped={len(drop)}")
