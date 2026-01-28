import os
import threading
import time

from trader_loop import trader_loop
from sell_engine import sell_engine


# --- LOAD_ENV_FILE_PATCH_V1 ---
import os
from pathlib import Path

def _load_env_file(path: str) -> None:
    try:
        p = Path(path)
        if not p.exists():
            return
        for line in p.read_text(encoding='utf-8', errors='ignore').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k,v = line.split('=',1)
            k=k.strip(); v=v.strip()
            if k and (k not in os.environ):
                os.environ[k]=v
    except Exception:
        pass

_load_env_file('state/jup_endpoints.env')

def _ensure_alias_env():
    # Jupiter
    os.environ.setdefault("JUP_BASE", os.getenv("JUPITER_BASE_URL", "https://api.jup.ag"))
    os.environ.setdefault("JUP_TOKENS_BASE", os.getenv("JUP_TOKENS_BASE", os.environ["JUP_BASE"].rstrip("/") + "/tokens/v2"))
    os.environ.setdefault("JUP_API_KEY", os.getenv("JUP_API_KEY", os.getenv("JUPITER_API_KEY", "")))

    # RPC
    os.environ.setdefault("RPC_HTTP", os.getenv("RPC_HTTP", os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")))

    # Wallet pubkey
    os.environ.setdefault("WALLET_PUBKEY", os.getenv("WALLET_PUBKEY", os.getenv("TRADER_USER_PUBLIC_KEY", "")))

    # Trade sizing / slippage
    os.environ.setdefault("TRADER_SOL_AMOUNT", os.getenv("TRADER_SOL_AMOUNT", os.getenv("BUY_AMOUNT_SOL", "0.01")))
    os.environ.setdefault("TRADER_SLIPPAGE_BPS", os.getenv("TRADER_SLIPPAGE_BPS", os.getenv("SLIPPAGE_BPS", "120")))
    os.environ.setdefault("TRADER_MAX_PRICE_IMPACT_PCT", os.getenv("TRADER_MAX_PRICE_IMPACT_PCT", os.getenv("MAX_PRICE_IMPACT_PCT", "1.5")))



def _real_mode_safety_guard():
    mode = (os.getenv("MODE","PAPER") or "PAPER").upper()
    if mode != "REAL":
        return
    pub = (os.getenv("WALLET_PUBKEY") or os.getenv("TRADER_USER_PUBLIC_KEY") or "").strip()
    keypair = os.getenv("TRADER_KEYPAIR_PATH", "keypair.json")
    if not pub:
        raise SystemExit("❌ MODE=REAL but missing WALLET_PUBKEY/TRADER_USER_PUBLIC_KEY")
    from pathlib import Path
    if not Path(keypair).exists():
        raise SystemExit(f"❌ MODE=REAL but missing keypair file: {keypair}")


def main():
    _ensure_alias_env()
    _real_mode_safety_guard()

    print("🚀 run_live: starting sell_engine + trader_loop", flush=True)

    # sell_engine en background (sinon il bloque)
    t = threading.Thread(target=sell_engine, name="sell_engine", daemon=True)
    t.start()

    # petite pause pour logs
    time.sleep(0.2)

    # trader loop au premier plan
    trader_loop()


if __name__ == "__main__":
    main()
