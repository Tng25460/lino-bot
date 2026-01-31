#!/usr/bin/env python3
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import aiohttp

# ---------------- CONFIG ----------------
MINTS_FOUND_PATH = Path(os.getenv("MINTS_FOUND_PATH", "mints_found.json"))
READY_PATH = Path(os.getenv("READY_PATH", "ready_to_trade.jsonl"))
STATE_PATH = Path(os.getenv("MINTS_CONSUMER_STATE", "mints_consumer_state.json"))

JUP_BASE = (os.getenv("JUPITER_BASE_URL") or "https://api.jup.ag").rstrip("/")
JUP_API_KEY = (os.getenv("JUPITER_API_KEY") or "").strip()

POLL_S = float(os.getenv("MINTS_CONSUMER_POLL_S", "1.5"))

# We quote: USDC -> mint
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
INPUT_MINT = os.getenv("INPUT_MINT", USDC_MINT).strip() or USDC_MINT

TEST_USDC_AMOUNT = int(os.getenv("TEST_USDC_AMOUNT", "1000000"))  # 1 USDC = 1_000_000
SLIPPAGE_BPS = int(os.getenv("SLIPPAGE_BPS", "500"))  # 5% for quote safety

MAX_PRICE_IMPACT_PCT = float(os.getenv("MAX_PRICE_IMPACT_PCT", "5.0"))  # 5%
MIN_OUT_AMOUNT = int(os.getenv("MIN_OUT_AMOUNT", "1"))

IGNORE_MINTS = {
    USDC_MINT,  # avoid circular
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}

# ---------------- HELPERS ----------------
def _jup_headers() -> Dict[str, str]:
    h = {"accept": "application/json"}
    if JUP_API_KEY:
        h["x-api-key"] = JUP_API_KEY
    return h


def load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {"last_ts": 0, "seen_mints": []}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8") or "{}")
        if not isinstance(data, dict):
            return {"last_ts": 0, "seen_mints": []}
        data.setdefault("last_ts", 0)
        data.setdefault("seen_mints", [])
        return data
    except Exception:
        return {"last_ts": 0, "seen_mints": []}


def save_state(state: Dict[str, Any]) -> None:
    try:
        STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except Exception:
        return


def read_mints_found() -> list:
    if not MINTS_FOUND_PATH.exists():
        return []
    try:
        data = json.loads(MINTS_FOUND_PATH.read_text(encoding="utf-8") or "[]")
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def append_ready(rec: Dict[str, Any]) -> None:
    """Append 1 record JSONL into READY_PATH. Safe."""
    try:
        READY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with READY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[append_ready] failed err={e}")


def quote_is_ok(q: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        out_amt = int(q.get("outAmount") or 0)
        if out_amt < MIN_OUT_AMOUNT:
            return False, "outAmount too low"
        pi = q.get("priceImpactPct")
        if pi is None:
            return False, "missing priceImpactPct"
        # Jupiter sometimes returns decimal string
        pi_f = float(pi)
        if pi_f * 100.0 > MAX_PRICE_IMPACT_PCT:
            return False, f"priceImpactPct too high ({pi_f*100:.4f}%)"
        return True, "ok"
    except Exception as e:
        return False, f"parse error: {e}"


def _looks_like_mint(m: str) -> bool:
    # base58 pubkey typical length 32..44, but some tokens can be a bit longer in logs
    if not isinstance(m, str):
        return False
    if " " in m or "\n" in m or "\t" in m:
        return False
    return 32 <= len(m) <= 60


async def jup_quote(session: aiohttp.ClientSession, out_mint: str) -> Optional[Dict[str, Any]]:
    # Jupiter swap quote endpoint
    url = f"{JUP_BASE}/swap/v1/swap/v1/quote"
    params = {
        "inputMint": INPUT_MINT,
        "outputMint": out_mint,
        "amount": str(TEST_USDC_AMOUNT),
        "slippageBps": str(SLIPPAGE_BPS),
    }
    try:
        async with session.get(url, params=params, headers=_jup_headers(), timeout=aiohttp.ClientTimeout(total=20)) as r:
            txt = await r.text()
            if r.status != 200:
                print(f"[JUP][HTTP {r.status}] {txt[:400]}")
                return None
            return json.loads(txt)
    except Exception as e:
        print(f"[JUP] quote failed err={e}")
        return None


# ---------------- MAIN ----------------
async def main() -> None:
    print("🚀 consumer Jupiter démarré")
    print(f"   file={MINTS_FOUND_PATH}")
    print(f"   jup_base={JUP_BASE}")
    print(f"   input_mint={INPUT_MINT}")
    print(f"   test_usdc_amount={TEST_USDC_AMOUNT} (base units)")
    print(f"   max_price_impact={MAX_PRICE_IMPACT_PCT}")

    st = load_state()
    last_ts = int(st.get("last_ts") or 0)
    seen = set(st.get("seen_mints") or [])

    async with aiohttp.ClientSession() as session:
        while True:
            rows = read_mints_found()
            # sort by ts asc
            rows = [r for r in rows if isinstance(r, dict)]
            rows.sort(key=lambda x: int(x.get("ts") or 0))

            for r in rows:
                ts = int(r.get("ts") or 0)
                if ts < last_ts:
                    continue

                mint = str(r.get("mint") or "")
                creator = str(r.get("creator") or "")
                pump_sig = str(r.get("pump_sig") or "")
                mint_sig = str(r.get("mint_sig") or "")

                # move cursor even on bad entries to avoid infinite loop
                if not mint:
                    last_ts = max(last_ts, ts + 1)
                    continue

                if mint in seen:
                    last_ts = max(last_ts, ts + 1)
                    continue

                print(f"\n🆕 NEW MINT: {mint} (creator={creator}) ts={ts}")

                # guards
                if not _looks_like_mint(mint):
                    print(f"   ⏭️  SKIP_MINT (invalid format): {mint}")
                    seen.add(mint)
                    last_ts = max(last_ts, ts + 1)
                    continue

                if mint in IGNORE_MINTS:
                    print(f"   ⏭️  SKIP_MINT (ignored): {mint}")
                    seen.add(mint)
                    last_ts = max(last_ts, ts + 1)
                    continue

                if mint == INPUT_MINT:
                    print(f"   ⏭️  SKIP_MINT (same as INPUT_MINT): {mint}")
                    seen.add(mint)
                    last_ts = max(last_ts, ts + 1)
                    continue

                q = await jup_quote(session, mint)
                if not q:
                    print("   ❌ Jupiter quote failed (no data)")
                    seen.add(mint)
                    last_ts = max(last_ts, ts + 1)
                    continue

                ok, reason = quote_is_ok(q)
                if ok:
                    out_amt = q.get("outAmount")
                    pi = q.get("priceImpactPct")
                    print(f"   ✅ QUOTE OK outAmount={out_amt} priceImpactPct={pi}")
                    print(f"   👉 READY_TO_TRADE mint={mint} pump_sig={pump_sig} mint_sig={mint_sig}")
                    append_ready({
                        "ts": ts,
                        "mint": mint,
                        "creator": creator,
                        "pump_sig": pump_sig,
                        "mint_sig": mint_sig,
                        "outAmount": out_amt,
                        "priceImpactPct": pi,
                    })
                else:
                    print(f"   🛑 QUOTE NOT OK reason={reason}")

                seen.add(mint)
                last_ts = max(last_ts, ts + 1)

                # persist state
                save_state({"last_ts": last_ts, "seen_mints": list(seen)[-5000:]})

            await asyncio.sleep(POLL_S)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 arrêt demandé (Ctrl+C).")
