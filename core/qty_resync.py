"""
PHASE3_P3.2: Module de resynchronisation post-buy qty_token.

Extrait de src/trader_exec.py sans modification de logique.
Fonctions:
  - _onchain_ui_balance_stable(mint, ...) : lecture on-chain du solde UI (RPC getTokenAccountsByOwner)
  - resync_buy_inline(output_mint, txsig) : resync best-effort couche 1/3

Couche 1: resync_buy_inline (ici, appelé immediatement apres BUY)
Couche 2: scripts/resync_buy_qty.py (appele par trader_loop.py apres rc=2)
Couche 3: sell_engine._onchain_ui_balance_simple() au moment du sell
"""
from __future__ import annotations
import os


def _onchain_ui_balance_stable(
    mint: str, tries: int = 3, sleep_s: float = 0.6, timeout_s: float = 4.0
) -> float:
    """
    Lit le solde UI on-chain pour un mint donne, avec retry + stabilite.
    Retourne le montant UI (float) ou 0.0 si echec.
    """
    import time, json
    import requests
    from solders.keypair import Keypair

    rpc = os.getenv("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
    keypath = os.getenv("KEYPAIR_PATH", "keypair.json")

    try:
        secret = json.load(open(keypath, "r", encoding="utf-8"))
        kp = Keypair.from_bytes(bytes(secret))
        owner = str(kp.pubkey())
    except Exception:
        return 0.0

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [owner, {"mint": mint}, {"encoding": "jsonParsed"}],
    }

    t0 = time.time()
    prev = None
    for _ in range(max(1, tries)):
        if time.time() - t0 > timeout_s:
            break
        try:
            j = requests.post(rpc, json=payload, timeout=25).json()
        except Exception:
            j = {}
        total = 0.0
        for a in j.get("result", {}).get("value", []) or []:
            try:
                ui = a["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"] or 0
                total += float(ui)
            except Exception:
                pass
        v = float(total)
        if prev is not None and abs(v - prev) <= max(1e-12, abs(prev) * 0.005):
            return v
        prev = v
        time.sleep(max(0.0, sleep_s))
    return float(prev or 0.0)


def resync_buy_inline(output_mint: str, txsig: str) -> bool:
    """
    PHASE1_P1.3: essai de resync inline best-effort (couche 1/3).
    Attend 1.5s puis lit le solde on-chain et met a jour trades+positions.
    Retourne True si resync OK, False sinon (non-fatal).
    """
    import time
    import sqlite3

    try:
        time.sleep(1.5)  # laisser le temps a la blockchain de confirmer
        _resync_qty = _onchain_ui_balance_stable(
            str(output_mint), tries=3, sleep_s=0.5, timeout_s=4.0
        )
        if _resync_qty and _resync_qty > 0:
            _rdb = os.getenv(
                "TRADES_DB_PATH", os.getenv("DB_PATH", "state/trades.sqlite")
            )
            _rcon = sqlite3.connect(_rdb, timeout=10)
            _rcur = _rcon.cursor()
            _rcur.execute(
                "UPDATE trades SET qty_token=? WHERE txsig=? AND (qty_token IS NULL OR qty_token=0)",
                (float(_resync_qty), txsig),
            )
            _rcur.execute(
                "UPDATE positions SET qty_token=? WHERE mint=? AND status='OPEN' AND (qty_token IS NULL OR qty_token=0)",
                (float(_resync_qty), output_mint),
            )
            _rcon.commit()
            _rcon.close()
            print(
                f"✅ RESYNC_INLINE: qty_token={_resync_qty} for {output_mint[:8]}…",
                flush=True,
            )
            return True
        else:
            print(
                f"⏳ RESYNC_INLINE: on-chain=0 (normal si tx pas encore confirmée), resync_buy_qty.py prendra le relai",
                flush=True,
            )
            return False
    except Exception as _re:
        print(
            f"⚠️ RESYNC_INLINE failed (non-fatal, resync_buy_qty.py backup): {_re}",
            flush=True,
        )
        return False
