import os, sys, subprocess

def main():
    # passthrough args to sell_exec.py
    cmd = [sys.executable, "-u", "src/sell_exec.py"] + sys.argv[1:]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ.copy())
    out = p.stdout or ""
    if out:
        print(out, end="" if out.endswith("\n") else "\n", flush=True)

    lo = out.lower()

    # 429
    if ("too many requests" in lo) or ("http 429" in lo) or (" 429 " in lo):
        print("HTTP_429", flush=True)
        raise SystemExit(43)

    # insufficient funds (fees / rent / lamports)
    if ("insufficient funds" in lo) or ("insufficient lamports" in lo) or ("jup_insufficient_funds" in lo) or ("insufficient_funds" in lo):
        print("INSUFFICIENT_FUNDS", flush=True)
        raise SystemExit(44)

    # route fail 0x1788
    if ("0x1788" in lo) or ("route_fail_0x1788" in lo):
        print("ROUTE_FAIL_0x1788", flush=True)
        raise SystemExit(42)

    raise SystemExit(p.returncode)

if __name__ == "__main__":
    main()
