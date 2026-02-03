#!/usr/bin/env python3
import os, time, json, sys
import requests

OUT=os.getenv("UNIVERSE_OUT","state/ready_from_tokenlist.jsonl")
MAX_N=int(os.getenv("UNIVERSE_TOKENLIST_MAX","1200"))
TIMEOUT=float(os.getenv("HTTP_TIMEOUT","30"))

URLS=[
  os.getenv("TOKENLIST_URL","").strip(),
  "https://token.jup.ag/all",
  "https://raw.githubusercontent.com/solana-labs/token-list/main/src/tokens/solana.tokenlist.json",
  "https://raw.githubusercontent.com/solana-labs/token-list/main/src/tokens/solana.tokenlist.json?raw=1",
]

def fetch(url:str):
  r=requests.get(url, timeout=TIMEOUT)
  r.raise_for_status()
  return r.json()

def iter_tokens(obj):
  # token.jup.ag/all => list[dict]
  if isinstance(obj, list):
    for t in obj:
      if isinstance(t, dict):
        yield t
    return
  # solana.tokenlist.json => {"tokens":[...]}
  if isinstance(obj, dict):
    toks=obj.get("tokens")
    if isinstance(toks, list):
      for t in toks:
        if isinstance(t, dict):
          yield t
      return
  raise SystemExit(f"Unexpected tokenlist format: {type(obj)}")

def get_mint(t:dict)->str:
  return (t.get("address") or t.get("mint") or t.get("symbolMint") or "").strip()

def main():
  last_err=None
  data=None
  used=None
  for url in [u for u in URLS if u]:
    try:
      data=fetch(url)
      used=url
      break
    except Exception as e:
      last_err=e
      print(f"[WARN] tokenlist fetch failed url={url} err={e}", flush=True)
  if data is None:
    raise SystemExit(f"[FATAL] all tokenlist urls failed: {last_err}")

  n=0
  t0=time.time()
  with open(OUT,"w",encoding="utf-8") as f:
    for t in iter_tokens(data):
      mint=get_mint(t)
      if not mint:
        continue
      o={"mint": mint}
      sym=(t.get("symbol") or "").strip()
      if sym: o["symbol"]=sym
      dec=t.get("decimals")
      if isinstance(dec, int): o["decimals"]=dec
      f.write(json.dumps(o,separators=(",",":"))+"\n")
      n += 1
      if n>=MAX_N:
        break

  dt=time.time()-t0
  print(f"[OK] tokenlist_url={used}", flush=True)
  print(f"[OK] wrote {n} -> {OUT} ({dt:.2f}s)", flush=True)

if __name__=="__main__":
  main()
