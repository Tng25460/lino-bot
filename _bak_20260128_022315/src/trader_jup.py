import asyncio
import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, List

import aiohttp


READY_PATH = Path(os.getenv("READY_PATH", "ready_to_trade.jsonl"))
STATE_PATH = Path(os.getenv("TRADER_STATE_PATH", "trader_state.json"))

JUP_BASE = (os.getenv("JUPITER_BASE_URL") or "https://api.jup.ag").rstrip("/")
JUP_API_KEY = (os.getenv("JUPITER_API_KEY") or "").strip()

# Base mint (input) = USDC par défaut
INPUT_MINT = os.getenv("TRADER_INPUT_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v").strip()

# 1 USDC = 1_000_000 (base units)
AMOUNT = int(os.getenv("TRADER_AMOUNT", "1000000"))

# slippage en bps (50 = 0.50%)
SLIPPAGE_BPS = int(os.getenv("TRADER_SLIPPAGE_BPS", "50"))

# polling
POLL_S = float(os.getenv("TRADER_POLL_S", "1.0"))

# test guards
MAX_PRICE_IMPACT_PCT = float(os.getenv("TRADER_MAX_PRICE_IMPACT_PCT", "5.0"))

# Par défaut: QUOTE only
BUILD_SWAP_TX = os.getenv("TRADER_BUILD_SWAP_TX", "0") == "1"

# Pour build une swap tx, il faut un userPublicKey
USER_PUBLIC_KEY = (os.getenv("TRADER_USER_PUBLIC_KEY") or "").strip()

# ignore obvious bases
IGNORE_MINTS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}

LAST_TX_B64_PATH = Path(os.getenv("TRADER_LAST_TX_B64_PATH", "last_swap_tx.b64"))


def _jup_headers() -> Dict[str, str]:
    h = {"accept": "application/json"}
    if JUP_API_KEY:
        h["x-api-key"] = JUP_API_KEY
    return h


def load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {"last_ts": 0}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8") or "{}") or {"last_ts": 0}
    except Exception:
        return {"last_ts": 0}


def save_state(st: Dict[str, Any]) -> None:
    try:
        STATE_PATH.write_text(json.dumps(st, indent=2), encoding="utf-8")
    except Exception:
        pass


def is_valid_mint(m: str) -> bool:
    # garde simple (évite les 400 Jupiter sur des strings fake)
    return isinstance(m, str) and 32 <= len(m) <= 60 and " " not in m


def parse_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out


async def jup_quote(session: aiohttp.ClientSession, out_mint: str) -> Optional[Dict[str, Any]]:
    url = f"{JUP_BASE}/swap/v1/swap/v1/quote"
    params = {
        "inputMint": INPUT_MINT,
        "outputMint": out_mint,
        "amount": str(AMOUNT),
        "slippageBps": str(SLIPPAGE_BPS),
        "onlyDirectRoutes": "false",
    }
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as r:
            txt = await r.text()
            if r.status != 200:
                print(f"[JUP][HTTP {r.status}] {txt[:400]}")
                return None
            return json.loads(txt)
    except Exception as e:
        print(f"[JUP][quote] err={e}")
        return None


def quote_is_ok(q: Dict[str, Any]) -> (bool, str):
    try:
        pi = q.get("priceImpactPct")
        # parfois string / parfois float
        pi_f = float(pi) if pi is not None else 0.0
        if pi_f * 100.0 > MAX_PRICE_IMPACT_PCT:
            return False, f"priceImpactPct={pi} > {MAX_PRICE_IMPACT_PCT}%"
        out_amt = q.get("outAmount")
        if not out_amt:
            return False, "no outAmount"
        return True, "ok"
    except Exception as e:
        return False, f"quote_parse_error={e}"


def summarize_route(q: Dict[str, Any]) -> str:
    out_amt = q.get("outAmount")
    pi = q.get("priceImpactPct")
    rp = q.get("routePlan") or []
    hops = len(rp) if isinstance(rp, list) else 0
    first = ""
    last = ""
    try:
        if hops >= 1:
            first = str((rp[0] or {}).get("swapInfo", {}).get("label") or "")
            last = str((rp[-1] or {}).get("swapInfo", {}).get("label") or "")
    except Exception:
        pass
    return f"outAmount={out_amt} priceImpactPct={pi} hops={hops} first={first} last={last}"


async def jup_build_swap_tx(session: aiohttp.ClientSession, quote: Dict[str, Any], user_pubkey: str) -> Optional[str]:
    """
    Build swap tx (base64) using Jupiter swap endpoint.
    DOES NOT send it.
    """
    url = f"{JUP_BASE}/swap/v1/swap"
    body = {
        "quoteResponse": quote,
        "userPublicKey": user_pubkey,
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": "auto",
    }
    try:
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=25)) as r:
            txt = await r.text()
            if r.status != 200:
                print(f"[JUP][SWAP_BUILD][HTTP {r.status}] {txt[:400]}")
                return None
            j = json.loads(txt)
            tx_b64 = j.get("swapTransaction")
            if not tx_b64:
                print("[JUP][SWAP_BUILD] missing swapTransaction")
                return None
            return str(tx_b64)
    except Exception as e:
        print(f"[JUP][swap_build] err={e}")
        return None


async def main():
    print("🚀 trader_jup démarré (TEST)")
    print(f"   ready_file={READY_PATH}")
    print(f"   jup_base={JUP_BASE}")
    print(f"   input_mint={INPUT_MINT}")
    print(f"   amount={AMOUNT} slippage_bps={SLIPPAGE_BPS}")
    print(f"   max_price_impact={MAX_PRICE_IMPACT_PCT}%")
    print(f"   build_swap_tx={BUILD_SWAP_TX}")
    if BUILD_SWAP_TX:
        print(f"   user_pubkey={(USER_PUBLIC_KEY[:6] + '...' + USER_PUBLIC_KEY[-6:]) if USER_PUBLIC_KEY else '(missing)'}")

    st = load_state()
    last_ts = int(st.get("last_ts") or 0)

    async with aiohttp.ClientSession(headers=_jup_headers()) as session:
        while True:
            rows = parse_jsonl(READY_PATH)

            # traite uniquement les nouveaux (ts > last_ts)
            new_rows = [r for r in rows if int(r.get("ts") or 0) > last_ts]
            new_rows.sort(key=lambda r: int(r.get("ts") or 0))

            for r in new_rows:
                ts = int(r.get("ts") or 0)
                mint = str(r.get("mint") or "")
                creator = str(r.get("creator") or "")
                pump_sig = str(r.get("pump_sig") or "")
                mint_sig = str(r.get("mint_sig") or "")

                print(f"\n🆕 READY: mint={mint} creator={creator} ts={ts}")
                if not is_valid_mint(mint):
                    print("   ⏭️  SKIP (invalid mint format)")
                    last_ts = max(last_ts, ts)
                    save_state({"last_ts": last_ts})
                    continue
                if mint in IGNORE_MINTS:
                    print("   ⏭️  SKIP (ignored mint)")
                    last_ts = max(last_ts, ts)
                    save_state({"last_ts": last_ts})
                    continue
                if mint == INPUT_MINT:
                    print("   ⏭️  SKIP (output == input)")
                    last_ts = max(last_ts, ts)
                    save_state({"last_ts": last_ts})
                    continue

                q = await jup_quote(session, mint)
                if not q:
                    print("   ❌ quote failed")
                    last_ts = max(last_ts, ts)
                    save_state({"last_ts": last_ts})
                    continue

                ok, reason = quote_is_ok(q)
                print("   📌 route:", summarize_route(q))
                if not ok:
                    print(f"   🛑 QUOTE NOT OK: {reason}")
                    last_ts = max(last_ts, ts)
                    save_state({"last_ts": last_ts})
                    continue

                print(f"   ✅ QUOTE OK -> candidate trade mint={mint} pump_sig={pump_sig} mint_sig={mint_sig}")

                if BUILD_SWAP_TX:
                    if not USER_PUBLIC_KEY:
                        print("   ⚠️ build_swap_tx=1 mais TRADER_USER_PUBLIC_KEY est vide -> skip build")
                    else:
                        tx_b64 = await jup_build_swap_tx(session, q, USER_PUBLIC_KEY)
                        if tx_b64:
                            LAST_TX_B64_PATH.write_text(tx_b64 + "\n", encoding="utf-8")
                            # sanity decode size
                            try:
                                raw = base64.b64decode(tx_b64)
                                print(f"   🧱 swap tx built: {LAST_TX_B64_PATH} (bytes={len(raw)})")
                            except Exception:
                                print(f"   🧱 swap tx built: {LAST_TX_B64_PATH}")

                # marque comme traité
                last_ts = max(last_ts, ts)
                save_state({"last_ts": last_ts})

            await asyncio.sleep(POLL_S)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 arrêt demandé (Ctrl+C).")
