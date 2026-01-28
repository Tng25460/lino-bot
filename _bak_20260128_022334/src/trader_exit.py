import os
import json
import time
import requests
from pathlib import Path

from src.positions import load_positions, mark_closed

JUP = (os.getenv("JUPITER_BASE_URL") or "https://api.jup.ag").rstrip("/")
KEY = (os.getenv("JUPITER_API_KEY") or "").strip()

OWNER = (os.getenv("TRADER_USER_PUBLIC_KEY","") or "").strip()
SOL = "So11111111111111111111111111111111111111112"

TP_PCT = float(os.getenv("EXIT_TP_PCT", "0.25"))     # +25%
SL_PCT = float(os.getenv("EXIT_SL_PCT", "0.12"))     # -12%
MAX_HOLD_S = int(os.getenv("EXIT_MAX_HOLD_S", str(6*3600)))

SLIPPAGE_BPS = int(os.getenv("EXIT_SLIPPAGE_BPS", "120"))
DRY_RUN = (os.getenv("EXIT_DRY_RUN", "1").strip().lower() in ("1","true","yes","on"))

def _headers():
    h = {"accept":"application/json"}
    if KEY:
        h["x-api-key"] = KEY
    return h

def quote_token_to_sol(mint: str, amount_raw: int):
    params = {
        "inputMint": mint,
        "outputMint": SOL,
        "amount": str(int(amount_raw)),
        "slippageBps": str(int(SLIPPAGE_BPS)),
    }
    r = requests.get(f"{JUP}/swap/v1/quote", params=params, headers=_headers(), timeout=25)
    r.raise_for_status()
    return r.json()

def main():
    if not OWNER:
        raise SystemExit("❌ TRADER_USER_PUBLIC_KEY manquant")

    pos = load_positions()
    now = int(time.time())
    open_pos = [p for p in pos if not p.get("closed_ts")]

    print("🧠 trader_exit open_positions=", len(open_pos), "dry_run=", DRY_RUN)

    for p in open_pos:
        mint = (p.get("mint") or "").strip()
        open_ts = int(p.get("open_ts") or 0)
        sol_spent = float(p.get("sol_spent") or 0.0)

        # token amount: on essaie token_ui_amount * 10^dec (approx)
        ui_amt = float(p.get("token_ui_amount") or 0.0)
        dec = int(p.get("token_decimals") or 0)
        amt_raw = int(ui_amt * (10 ** dec))

        if amt_raw <= 0:
            print("   ⏭️ skip mint(no amount)", mint[:6], "ui_amt=", ui_amt, "dec=", dec)
            continue

        # timeout
        held_s = now - open_ts
        timeout_hit = held_s >= MAX_HOLD_S

        # quote token->SOL
        try:
            q = quote_token_to_sol(mint, amt_raw)
        except Exception as e:
            print("   ⚠️ quote fail", mint[:6], e)
            continue

        out_lamports = int(q.get("outAmount") or 0)
        sol_now = out_lamports / 1e9

        # pnl
        if sol_spent <= 0:
            pnl = 0.0
        else:
            pnl = (sol_now - sol_spent) / sol_spent

        tp_hit = pnl >= TP_PCT
        sl_hit = pnl <= -SL_PCT

        print(f"   mint={mint[:6]} held={held_s//60}m sol_spent={sol_spent:.6f} sol_now={sol_now:.6f} pnl={pnl*100:.1f}% tp={tp_hit} sl={sl_hit} timeout={timeout_hit}")

        if not (tp_hit or sl_hit or timeout_hit):
            continue

        reason = "TP" if tp_hit else ("SL" if sl_hit else "TIMEOUT")
        if DRY_RUN:
            print("   ✅ would SELL reason=", reason)
            continue

        # Pour SELL réel : on réutilise TON pipeline existant (build/sign/send) mais il faut un SELL builder.
        # On garde ça simple ici: on marque "signal sell" et on laisse un autre module builder la tx.
        # (On ajoute le builder SELL à l’étape suivante)
        print("   🔥 SELL SIGNAL ->", reason, "mint=", mint)
        # mark as closed signal only (no tx yet)
        mark_closed(mint, close_sig="PENDING", reason=reason)

if __name__ == "__main__":
    main()
