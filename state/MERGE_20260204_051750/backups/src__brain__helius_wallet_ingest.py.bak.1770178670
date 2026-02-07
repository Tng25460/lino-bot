#!/usr/bin/env python3
import os
import time
import json
import sqlite3
import traceback
from typing import Any, Dict, List, Optional, Tuple

import requests

# Env
BRAIN_DB = os.getenv("BRAIN_DB", "state/brain.sqlite")
HELIUS_URL = os.getenv("HELIUS_URL", "").strip()  # full RPC URL (https://.../?api-key=...)
OWNER = os.getenv("SELL_OWNER_PUBKEY", "").strip()

TICK_SEC = float(os.getenv("BRAIN_WALLET_TICK_SEC", "15"))
LIMIT = int(os.getenv("BRAIN_WALLET_LIMIT", "20"))

TIMEOUT = float(os.getenv("BRAIN_HTTP_TIMEOUT", "15"))
UA = os.getenv("BRAIN_UA", "lino-brain/1.0")

def die(msg: str) -> None:
    print(msg, flush=True)
    raise SystemExit(2)

def ensure_table(con: sqlite3.Connection) -> None:
    con.execute("""
    CREATE TABLE IF NOT EXISTS wallet_events (
      ts          INTEGER NOT NULL,
      owner       TEXT    NOT NULL,
      signature   TEXT    NOT NULL,
      slot        INTEGER,
      err         TEXT,
      kind        TEXT,
      mint        TEXT,
      amount      REAL,
      sol_change  REAL,
      fee_sol     REAL,
      source      TEXT,
      raw_json    TEXT,
      PRIMARY KEY(signature)
    )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_wallet_events_ts ON wallet_events(ts)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_wallet_events_owner_ts ON wallet_events(owner, ts)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_wallet_events_mint_ts ON wallet_events(mint, ts)")
    con.commit()

def rpc_call(url: str, method: str, params: list) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(url, json=payload, timeout=TIMEOUT, headers={"User-Agent": UA})
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(f"RPC error {j['error']}")
    return j.get("result")

def get_sigs_for_address(url: str, owner: str, limit: int) -> List[Dict[str, Any]]:
    # getSignaturesForAddress: returns newest->oldest
    return rpc_call(url, "getSignaturesForAddress", [owner, {"limit": limit}]) or []

def get_tx(url: str, signature: str) -> Optional[Dict[str, Any]]:
    # jsonParsed is convenient; maxSupportedTransactionVersion prevents version issues
    return rpc_call(url, "getTransaction", [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])

def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None

def compute_sol_change_and_fee(tx: Dict[str, Any], owner: str) -> Tuple[Optional[float], Optional[float]]:
    # SOL change = (post - pre) for the owner account index if we can locate it
    # Fee = meta.fee lamports
    try:
        meta = tx.get("meta") or {}
        fee_lamports = meta.get("fee")
        fee_sol = None if fee_lamports is None else float(fee_lamports) / 1e9

        msg = (tx.get("transaction") or {}).get("message") or {}
        keys = msg.get("accountKeys") or []
        # accountKeys in jsonParsed can be list of dicts or strings
        key_strs = []
        for k in keys:
            if isinstance(k, str):
                key_strs.append(k)
            elif isinstance(k, dict) and "pubkey" in k:
                key_strs.append(k["pubkey"])
            else:
                key_strs.append(str(k))

        if owner in key_strs:
            idx = key_strs.index(owner)
            pre = (meta.get("preBalances") or [])[idx]
            post = (meta.get("postBalances") or [])[idx]
            sol_change = (float(post) - float(pre)) / 1e9
        else:
            sol_change = None

        return sol_change, fee_sol
    except Exception:
        return None, None

def compute_token_delta(tx: Dict[str, Any], owner: str) -> Tuple[Optional[str], Optional[float]]:
    # Try to infer mint + delta amount for owner from pre/postTokenBalances
    # Returns (mint, delta_ui_amount) if detectable
    try:
        meta = tx.get("meta") or {}
        pre = meta.get("preTokenBalances") or []
        post = meta.get("postTokenBalances") or []

        def key(b: Dict[str, Any]) -> Tuple[str, str]:
            return (str(b.get("owner")), str(b.get("mint")))

        pre_map: Dict[Tuple[str, str], float] = {}
        for b in pre:
            k = key(b)
            ui = (((b.get("uiTokenAmount") or {}).get("uiAmount")) if isinstance(b.get("uiTokenAmount"), dict) else None)
            pre_map[k] = _to_float(ui) or 0.0

        post_map: Dict[Tuple[str, str], float] = {}
        for b in post:
            k = key(b)
            ui = (((b.get("uiTokenAmount") or {}).get("uiAmount")) if isinstance(b.get("uiTokenAmount"), dict) else None)
            post_map[k] = _to_float(ui) or 0.0

        # find biggest absolute delta for this owner (excluding None mint)
        best_mint = None
        best_delta = 0.0
        for (own, mint), post_amt in post_map.items():
            if own != owner:
                continue
            pre_amt = pre_map.get((own, mint), 0.0)
            d = post_amt - pre_amt
            if abs(d) > abs(best_delta) + 1e-12:
                best_delta = d
                best_mint = mint

        # Also consider tokens that disappeared (present in pre but not post)
        for (own, mint), pre_amt in pre_map.items():
            if own != owner:
                continue
            post_amt = post_map.get((own, mint), 0.0)
            d = post_amt - pre_amt
            if abs(d) > abs(best_delta) + 1e-12:
                best_delta = d
                best_mint = mint

        if best_mint is None or abs(best_delta) < 1e-12:
            return None, None
        return best_mint, float(best_delta)
    except Exception:
        return None, None

def infer_kind(tx: Optional[Dict[str, Any]]) -> str:
    # Minimal heuristic: "swap" if we see Jupiter program mention, else "tx"
    try:
        if not tx:
            return "sig"
        msg = (tx.get("transaction") or {}).get("message") or {}
        instrs = msg.get("instructions") or []
        text = json.dumps(instrs)
        if "Jupiter" in text or "jup" in text.lower():
            return "swap"
        return "tx"
    except Exception:
        return "tx"

def insert_event(con: sqlite3.Connection, row: Dict[str, Any]) -> bool:
    # returns True if inserted
    cols = ["ts","owner","signature","slot","err","kind","mint","amount","sol_change","fee_sol","source","raw_json"]
    vals = [row.get(c) for c in cols]
    q = "INSERT OR IGNORE INTO wallet_events (" + ",".join(cols) + ") VALUES (" + ",".join(["?"]*len(cols)) + ")"
    cur = con.execute(q, vals)
    con.commit()
    return cur.rowcount == 1

def main() -> None:
    if not HELIUS_URL:
        die("WALLET_INGEST fatal: HELIUS_URL missing")
    if not OWNER:
        die("WALLET_INGEST fatal: SELL_OWNER_PUBKEY missing")

    os.makedirs(os.path.dirname(BRAIN_DB) or ".", exist_ok=True)
    con = sqlite3.connect(BRAIN_DB)
    ensure_table(con)

    print(f"WALLET_INGEST start owner={OWNER} db={BRAIN_DB} tick={TICK_SEC:.1f}s limit={LIMIT}", flush=True)

    while True:
        try:
            sigs = get_sigs_for_address(HELIUS_URL, OWNER, LIMIT)
            inserted = 0

            for s in sigs:
                signature = s.get("signature")
                if not signature:
                    continue

                slot = s.get("slot")
                err = s.get("err")
                err_s = None if err is None else json.dumps(err, separators=(",",":"))

                tx = None
                try:
                    tx = get_tx(HELIUS_URL, signature)
                except Exception as e:
                    # Still store signature-only event if tx fetch fails
                    tx = None

                sol_change, fee_sol = (None, None)
                mint, amount = (None, None)
                if tx:
                    sol_change, fee_sol = compute_sol_change_and_fee(tx, OWNER)
                    mint, amount = compute_token_delta(tx, OWNER)

                row = {
                    "ts": int(time.time()),
                    "owner": OWNER,
                    "signature": signature,
                    "slot": int(slot) if slot is not None else None,
                    "err": err_s,
                    "kind": infer_kind(tx),
                    "mint": mint,
                    "amount": amount,
                    "sol_change": sol_change,
                    "fee_sol": fee_sol,
                    "source": "rpc",
                    "raw_json": json.dumps(tx if tx is not None else {"sig": signature}, separators=(",",":")),
                }

                if insert_event(con, row):
                    inserted += 1

            print(f"WALLET_INGEST tick sigs={len(sigs)} inserted={inserted}", flush=True)
        except KeyboardInterrupt:
            raise
        except Exception:
            print("WALLET_INGEST error:\n" + traceback.format_exc(), flush=True)

        time.sleep(TICK_SEC)

if __name__ == "__main__":
    main()
