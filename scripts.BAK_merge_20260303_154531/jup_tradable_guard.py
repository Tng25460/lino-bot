#!/usr/bin/env python3
import sys, json

raw = sys.stdin.read().strip()
if not raw:
    sys.exit(0)

try:
    j = json.loads(raw)
except Exception:
    sys.exit(0)

# Pas encore enrichi → OK
if "jup_error" not in j:
    print(json.dumps(j))
    sys.exit(0)

if j.get("jup_error") == "TOKEN_NOT_TRADABLE":
    sys.exit(1)

print(json.dumps(j))
