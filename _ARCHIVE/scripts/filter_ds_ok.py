#!/usr/bin/env python3
import os, json
INP=os.getenv("ENRICH_IN","state/ready_enriched.jsonl")
OUT=os.getenv("ENRICH_OUT","state/ready_enriched.dsok.jsonl")
tot=0; ok=0; bad=0
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
        if j.get("ds_ok") is True and (j.get("pair_address") or ""):
            ok += 1
            g.write(json.dumps(j, separators=(",",":"))+"\n")
print(f"[OK] ds_ok filter: in={INP} total={tot} bad={bad} kept={ok} out={OUT}")
