import sys, json, re
rx = re.compile(r"^[A-Z]{1,6}x$")

for line in sys.stdin:
    line=line.strip()
    if not line:
        continue
    try:
        o=json.loads(line)
    except Exception:
        continue
    sym=(o.get("symbol") or "").strip()
    name=(o.get("name") or "").strip().lower()

    if rx.match(sym):
        continue
    if any(k in name for k in ["stock","equity","etf","tokenized","xstock","shares"]):
        continue

    sys.stdout.write(json.dumps(o, ensure_ascii=False) + "\n")
