import json
import os
import subprocess
import time
from pathlib import Path

from src.rpc_token_balance import get_token_ui_amount

# Files
READY = Path(os.getenv("TRADER_READY_FILE", "ready_to_trade.jsonl"))
META = Path(os.getenv("TRADER_LAST_META_FILE", "last_swap_meta.json"))

USER = (os.getenv("TRADER_USER_PUBLIC_KEY","") or "").strip()
if not USER:
    raise SystemExit("❌ TRADER_USER_PUBLIC_KEY manquant")

def run(cmd):
    env = os.environ.copy()
    return subprocess.call(cmd, env=env)

def main():
    mint = (os.getenv("SELL_MINT","") or "").strip()
    pct = float(os.getenv("SELL_PCT","25"))
    if not mint:
        raise SystemExit("❌ SELL_MINT manquant")

    bal = float(get_token_ui_amount(os.getenv("SOLANA_RPC_HTTP","https://api.mainnet-beta.solana.com"), USER, mint) or 0.0)
    if bal <= 0:
        print("⏭️  no token balance to sell for", mint[:6]+"...")
        return

    amt = bal * (pct/100.0)
    if amt <= 0:
        print("⏭️  computed sell amount <=0")
        return

    # inject ready event for trader_exec (it reads ready_to_trade.jsonl)
    rec = {"ts": int(time.time()), "mint": mint, "creator": "PUMP_RIDER_SELL", "pump_sig": "X", "mint_sig": "Y"}
    READY.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    # IMPORTANT: sell = input mint is token, output = SOL mint (So111...)
    os.environ["TRADER_INPUT_MINT"] = mint
    os.environ["TRADER_OUTPUT_MINT"] = "So11111111111111111111111111111111111111112"

    # pass token amount in UI units (your trader_exec must read this env if present)
    os.environ["TRADER_FORCE_TOKEN_UI_AMOUNT"] = f"{amt:.9f}"

    print(f"🧾 SELL request mint={mint[:6]}... pct={pct}% bal={bal:.6f} -> amt={amt:.6f}")

    if run(["python","src/trader_exec.py"]) != 0:
        raise SystemExit("❌ trader_exec sell failed")
    if run(["python","src/trader_sign.py"]) != 0:
        raise SystemExit("❌ trader_sign failed")
    if run(["python","src/trader_send.py"]) != 0:
        raise SystemExit("❌ trader_send failed")

if __name__ == "__main__":
    main()
