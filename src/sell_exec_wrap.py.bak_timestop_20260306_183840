#!/usr/bin/env python3
"""
Stable wrapper around src/sell_exec.py

Maps common Jupiter / RPC failures to stable exit codes:

42 -> __ROUTE_FAIL__
43 -> __JUP_INSUFFICIENT_FUNDS__
44 -> __JUP_HTTP_429__
45 -> __TOKEN_NOT_TRADABLE__

Also supports a simulation mode to test SellEngine without touching Jupiter:
- export SELL_WRAP_SIMULATE_MAP='{"<mint>":"not_tradable|route_fail|429|insufficient"}'
If mint is in map, wrapper prints marker and exits with the mapped rc.
"""

import json
import re
import subprocess
import sys
from typing import Dict

RC_ROUTE_FAIL = 42
RC_INSUFF     = 43
RC_HTTP_429   = 44
RC_NOT_TRAD   = 45

def _parse_args(argv):
    mint = None
    ui = None
    reason = None
    for i,a in enumerate(argv):
        if a == "--mint" and i+1 < len(argv): mint = argv[i+1]
        if a == "--ui"   and i+1 < len(argv): ui   = argv[i+1]
        if a == "--reason" and i+1 < len(argv): reason = argv[i+1]
    return mint, ui, reason

def _load_sim_map() -> Dict[str,str]:
    raw = (sys.environ.get("SELL_WRAP_SIMULATE_MAP") if hasattr(sys, "environ") else None)
    if raw is None:
        import os
        raw = os.getenv("SELL_WRAP_SIMULATE_MAP", "")
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        j = json.loads(raw)
        if isinstance(j, dict):
            return {str(k): str(v) for k,v in j.items()}
    except Exception:
        pass
    return {}

def classify_output(text: str) -> int:
    low = (text or "").lower()

    if "__token_not_tradable__" in low or "token_not_tradable" in low:
        return RC_NOT_TRAD

    if "__jup_http_429__" in low or "__429__" in low or " 429 " in low:
        return RC_HTTP_429

    if "__jup_insufficient_funds__" in low or "__insufficient__" in low:
        return RC_INSUFF
    if "insufficient funds" in low or "not enough" in low:
        return RC_INSUFF

    if "__route_fail__" in low or "could not find any route" in low or "no route" in low or "0x1788" in low:
        return RC_ROUTE_FAIL

    if "fatal:" in low and "400" in low:
        # default 400 -> treat as not tradable
        return RC_NOT_TRAD

    return 0

def main():
    import os
    mint, ui, reason = _parse_args(sys.argv[1:])
    sim = _load_sim_map()

    if mint and mint in sim:
        mode = sim[mint].strip().lower()
        if mode in ("not_tradable","nottradable","token_not_tradable"):
            print("__TOKEN_NOT_TRADABLE__", flush=True); raise SystemExit(RC_NOT_TRAD)
        if mode in ("route_fail","routefail"):
            print("__ROUTE_FAIL__", flush=True); raise SystemExit(RC_ROUTE_FAIL)
        if mode in ("429","http_429","rate_limit","ratelimit"):
            print("__JUP_HTTP_429__", flush=True); raise SystemExit(RC_HTTP_429)
        if mode in ("insufficient","insufficient_funds","funds"):
            print("__JUP_INSUFFICIENT_FUNDS__", flush=True); raise SystemExit(RC_INSUFF)
        # unknown sim mode -> nonzero
        print("__SIM_UNKNOWN__", mode, flush=True); raise SystemExit(1)

    cmd = [sys.executable, "-u", "src/sell_exec.py"] + sys.argv[1:]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ.copy())

    out = p.stdout or ""
    if out:
        sys.stdout.write(out)
        if not out.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()

    # if child success -> success
    if p.returncode == 0:
        return 0

    # map failures by output
    rc = classify_output(out)
    if rc:
        # print marker line so SellEngine can grep if it wants
        if rc == RC_NOT_TRAD:  print("__TOKEN_NOT_TRADABLE__", flush=True)
        if rc == RC_ROUTE_FAIL: print("__ROUTE_FAIL__", flush=True)
        if rc == RC_HTTP_429:  print("__JUP_HTTP_429__", flush=True)
        if rc == RC_INSUFF:    print("__JUP_INSUFFICIENT_FUNDS__", flush=True)
        raise SystemExit(rc)

    # fallback: nonzero but unknown
    raise SystemExit(1)

if __name__ == "__main__":
    main()
