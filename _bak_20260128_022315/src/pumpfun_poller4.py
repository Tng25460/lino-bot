#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

# ---------------- CONFIG ----------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

RPC_HTTP = os.getenv("SOLANA_RPC_HTTP", "https://api.mainnet-beta.solana.com").rstrip("/")
PUMPFUN_PROGRAM = os.getenv("PUMPFUN_PROGRAM", "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")

RECENT_WINDOW_S = float(os.getenv("PUMPFUN_RECENT_WINDOW_S", "45"))  # ignore older tx
POLL_S = float(os.getenv("PUMPFUN_POLL_S", "1.0"))

HEARTBEAT_S = float(os.getenv("HEARTBEAT_S", "5.0"))

MINTS_FOUND_PATH = os.getenv("MINTS_FOUND_PATH", "mints_found.json")
MINTS_FOUND_MAX = int(os.getenv("MINTS_FOUND_MAX", "200"))

# ignore obvious base mints if you want
IGNORE_MINTS = {
    "So11111111111111111111111111111111111111112",  # WSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}

# ---------------- LOGGING ----------------
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("pumpfun_poller4")


def mask_creator(s: str) -> str:
    if not s:
        return ""
    if len(s) <= 8:
        return s
    return f"{s[:4]}…{s[-4:]}"


def hash_creator(s: str) -> str:
    # stable small hash for logs
    return hex(abs(hash(s)) % (1 << 32))[2:]


# ---------------- RPC HELPERS ----------------
async def rpc(session: aiohttp.ClientSession, method: str, params: list) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        async with session.post(RPC_HTTP, json=payload, timeout=aiohttp.ClientTimeout(total=25)) as r:
            txt = await r.text()
            if r.status != 200:
                log.warning("[RPC][HTTP %s] %s", r.status, txt[:400])
                return None
            j = json.loads(txt)
            if "error" in j:
                log.warning("[RPC][ERR] %s", j["error"])
                return None
            return j.get("result")
    except Exception as e:
        log.warning("[RPC] failed method=%s err=%s", method, e)
        return None


async def get_sigs(session: aiohttp.ClientSession, address: str, limit: int = 20) -> List[Dict[str, Any]]:
    res = await rpc(session, "getSignaturesForAddress", [address, {"limit": int(limit)}])
    return res or []


async def get_tx(session: aiohttp.ClientSession, signature: str) -> Optional[Dict[str, Any]]:
    # jsonParsed makes it easier for initializeMint
    res = await rpc(
        session,
        "getTransaction",
        [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
    )
    if not res:
        return None
    return res


# ---------------- MINT EXTRACTION ----------------
def extract_mint_from_pump_tx(tx: dict) -> Optional[str]:
    """
    Best-effort mint extraction from a pump.fun tx.
    Priority:
      1) meta.postTokenBalances[].mint
      2) parsed initializeMint / initializeMint2 (outer + inner)
    """
    if not isinstance(tx, dict):
        return None
    meta = tx.get("meta") or {}

    # (1) postTokenBalances
    for bal in (meta.get("postTokenBalances") or []):
        if isinstance(bal, dict):
            m = bal.get("mint")
            if m:
                return str(m)

    t = tx.get("transaction") or {}
    msg = t.get("message") or {}

    def scan(instrs):
        for ix in instrs or []:
            if not isinstance(ix, dict):
                continue
            parsed = ix.get("parsed")
            if not isinstance(parsed, dict):
                continue
            typ = (parsed.get("type") or "").lower()
            if typ in ("initializemint", "initializemint2"):
                info = parsed.get("info") or {}
                m = info.get("mint")
                if m:
                    return str(m)
        return None

    m = scan(msg.get("instructions") or [])
    if m:
        return m

    # inner instructions
    inner = (meta.get("innerInstructions") or [])
    for blk in inner:
        if not isinstance(blk, dict):
            continue
        m = scan(blk.get("instructions") or [])
        if m:
            return m
    return None


def extract_creator_from_tx(tx: dict) -> str:
    """
    Best-effort: fee payer / first account key.
    """
    try:
        t = tx.get("transaction") or {}
        msg = t.get("message") or {}
        keys = msg.get("accountKeys") or []
        if keys and isinstance(keys[0], dict) and "pubkey" in keys[0]:
            return str(keys[0]["pubkey"])
        if keys and isinstance(keys[0], str):
            return str(keys[0])
    except Exception:
        pass
    return ""


# ---------------- PERSIST ----------------
def record_mint_found(mint: str, creator: str, pump_sig: str, mint_sig: str) -> None:
    """Append un record dans mints_found.json. Safe (ne raise jamais)."""
    try:
        path = Path(MINTS_FOUND_PATH)
        rec = {
            "ts": int(time.time()),
            "mint": str(mint),
            "creator": str(creator),
            "pump_sig": str(pump_sig),
            "mint_sig": str(mint_sig),
        }

        data: list = []
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "[]")
                if not isinstance(data, list):
                    data = []
            except Exception:
                data = []

        data.append(rec)
        data = data[-int(MINTS_FOUND_MAX):]
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except Exception:
        return


# ---------------- MAIN LOOP ----------------
async def main() -> None:
    log.info("🚀 Pump.fun POLLER v4 (MINT_FOUND) démarré")
    log.info("   pumpfun_program=%s", PUMPFUN_PROGRAM)
    log.info("   rpc_http=%s", RPC_HTTP)
    log.info("   recent_window=%ss", RECENT_WINDOW_S)

    seen_sigs: set[str] = set()
    last_hb = 0.0

    async with aiohttp.ClientSession() as session:
        while True:
            now = time.time()
            if now - last_hb >= HEARTBEAT_S:
                log.info("[HEARTBEAT] loop alive")
                last_hb = now

            sigs = await get_sigs(session, PUMPFUN_PROGRAM, limit=25)

            # oldest -> newest processing so we don't miss bursts
            for it in reversed(sigs):
                sig = (it or {}).get("signature")
                if not sig or sig in seen_sigs:
                    continue

                block_time = (it or {}).get("blockTime") or 0
                age = now - float(block_time) if block_time else 999999
                if block_time and age > RECENT_WINDOW_S:
                    continue

                seen_sigs.add(sig)

                tx = await get_tx(session, sig)
                if not tx:
                    continue

                mint = extract_mint_from_pump_tx(tx)
                if not mint or mint in IGNORE_MINTS:
                    continue

                creator = extract_creator_from_tx(tx)

                log.error(
                    "🔥 [MINT_FOUND] mint=%s creator=%s#%s pump_sig=%s mint_sig=%s",
                    mint,
                    mask_creator(creator),
                    hash_creator(creator),
                    sig,
                    sig,
                )
                record_mint_found(mint, creator, sig, sig)

            # small cap to avoid memory blow
            if len(seen_sigs) > 20000:
                seen_sigs = set(list(seen_sigs)[-10000:])

            await asyncio.sleep(POLL_S)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 arrêt demandé (Ctrl+C).")
