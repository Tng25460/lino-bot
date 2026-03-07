import os, time, sqlite3, random, math
import requests

DB  = os.getenv("TRADES_DB_PATH", os.getenv("DB_PATH", "state/trades.sqlite"))
RPC = os.getenv("RPC_HTTP", os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"))
OWNER = (os.getenv("WALLET_PUBKEY") or os.getenv("TRADER_USER_PUBLIC_KEY") or "").strip()

# combien de BUY on traite par run (évite de se faire rate-limit)
LIMIT = int(os.getenv("REPAIR_LIMIT", "120"))

# backoff RPC
TRIES = int(os.getenv("REPAIR_TRIES", "8"))
BASE_SLEEP = float(os.getenv("REPAIR_BASE_SLEEP", "1.5"))
MAX_SLEEP  = float(os.getenv("REPAIR_MAX_SLEEP", "10"))

if not OWNER:
    print("❌ missing WALLET_PUBKEY/TRADER_USER_PUBLIC_KEY")
    raise SystemExit(2)

def rpc(method, params, timeout=25):
    r = requests.post(RPC, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=timeout)
    if r.status_code == 429:
        raise RuntimeError("RPC_429")
    r.raise_for_status()
    j = r.json()
    if isinstance(j, dict) and j.get("error"):
        raise RuntimeError(str(j["error"]))
    return j.get("result")

def get_tx(sig):
    # jsonParsed = plus simple pour token balances
    return rpc("getTransaction", [sig, {"encoding":"jsonParsed","maxSupportedTransactionVersion":0}], timeout=35)

def _flt(x):
    try:
        return float(x)
    except Exception:
        return 0.0

def extract_buy_deltas(tx, owner, mint):
    """
    Retourne (sol_spent, token_received_ui) pour owner et mint.
    Heuristique:
      - SOL delta: postBalance - preBalance (lamports), on prend dépense = -(delta) en SOL si negatif
      - Token delta: somme(post - pre) pour ce mint sur owner
    """
    if not tx:
        return 0.0, 0.0

    meta = tx.get("meta") or {}
    if meta.get("err") is not None:
        # tx failed
        return 0.0, 0.0

    # SOL delta
    sol_spent = 0.0
    try:
        keys = (tx.get("transaction") or {}).get("message", {}).get("accountKeys", [])
        # keys peut être list[dict] (jsonParsed)
        idx = None
        for i, k in enumerate(keys):
            pub = k.get("pubkey") if isinstance(k, dict) else k
            if pub == owner:
                idx = i
                break
        if idx is not None:
            pre = (meta.get("preBalances") or [])[idx]
            post = (meta.get("postBalances") or [])[idx]
            delta_sol = (post - pre) / 1e9
            if delta_sol < 0:
                sol_spent = -delta_sol
    except Exception:
        pass

    # Token delta (ui amount)
    token_ui = 0.0
    try:
        pre_tb  = meta.get("preTokenBalances")  or []
        post_tb = meta.get("postTokenBalances") or []

        def by_key(lst):
            d = {}
            for it in lst:
                if (it.get("mint") == mint) and (it.get("owner") == owner):
                    # accountIndex est le lien
                    d[it.get("accountIndex")] = it
            return d

        pre_d  = by_key(pre_tb)
        post_d = by_key(post_tb)

        idxs = set(pre_d.keys()) | set(post_d.keys())
        for ai in idxs:
            pre_it  = pre_d.get(ai)  or {}
            post_it = post_d.get(ai) or {}
            pre_ui  = _flt(((pre_it.get("uiTokenAmount") or {}).get("uiAmount")) or 0.0)
            post_ui = _flt(((post_it.get("uiTokenAmount") or {}).get("uiAmount")) or 0.0)
            token_ui += (post_ui - pre_ui)

        if token_ui < 0:
            # si c'est négatif, ce n'est pas un BUY net (ou multi-mouvements)
            token_ui = 0.0
    except Exception:
        pass

    return float(sol_spent), float(token_ui)

def retry_get(sig):
    last_err = None
    for k in range(TRIES):
        try:
            return get_tx(sig)
        except Exception as e:
            last_err = e
            if "RPC_429" in str(e) or "429" in str(e):
                sleep_s = min(MAX_SLEEP, BASE_SLEEP * (1.7 ** k)) + random.random()*0.25
                time.sleep(sleep_s)
                continue
            # autres erreurs: petit délai puis retry
            time.sleep(0.6 + random.random()*0.2)
    raise RuntimeError(f"getTransaction failed: {last_err}")

def main():
    print(f"🧰 repair_buy_from_txsig DB={DB} RPC={RPC} OWNER={OWNER} LIMIT={LIMIT}", flush=True)
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # trades schema: ts, side, mint, qty_token, price, txsig, qty
    rows = cur.execute(
        """
        SELECT id, ts, mint, txsig
        FROM trades
        WHERE side='BUY'
          AND (COALESCE(qty,0)=0 OR COALESCE(qty_token,0)=0 OR COALESCE(price,0)=0)
          AND COALESCE(txsig,'')!=''
        ORDER BY ts DESC
        LIMIT ?
        """,
        (LIMIT,)
    ).fetchall()

    print(f"found={len(rows)} candidates", flush=True)

    upd = 0
    skip = 0
    for _id, ts, mint, sig in rows:
        try:
            tx = retry_get(sig)
            sol_spent, tok_ui = extract_buy_deltas(tx, OWNER, mint)
            if sol_spent > 0 and tok_ui > 0:
                px = sol_spent / tok_ui
                cur.execute(
                    "UPDATE trades SET qty=?, qty_token=?, price=? WHERE id=?",
                    (float(sol_spent), float(tok_ui), float(px), _id)
                )
                con.commit()
                upd += 1
                print(f"✅ trade id={_id} mint={mint[:8]}… sol={sol_spent:.6f} tok={tok_ui:.6f} px={px:.12f}", flush=True)
            else:
                skip += 1
                print(f"⚠️ skip id={_id} mint={mint[:8]}… sol={sol_spent} tok={tok_ui}", flush=True)
        except Exception as e:
            skip += 1
            print(f"❌ err id={_id} mint={mint[:8]}… {e}", flush=True)

    # Maintenant: positions.entry_price depuis le BUY le plus proche (même mint)
    # NB: ta tentative SQL a planté car dans le sous-select tu ne peux pas référencer positions.entry_ts comme ça.
    # On fait un update via requêtes python.
    pos = cur.execute(
        "SELECT id, mint, entry_ts, qty_token FROM positions WHERE status LIKE 'OPEN%' AND COALESCE(entry_price,0)=0"
    ).fetchall()

    p_upd = 0
    for pid, mint, entry_ts, qty_token in pos:
        t = cur.execute(
            """
            SELECT price
            FROM trades
            WHERE side='BUY' AND mint=? AND COALESCE(price,0)>0
            ORDER BY ABS(ts - ?) ASC
            LIMIT 1
            """,
            (mint, int(entry_ts or 0))
        ).fetchone()
        if t and t[0]:
            cur.execute("UPDATE positions SET entry_price=? WHERE id=? AND COALESCE(entry_price,0)=0", (float(t[0]), pid))
            p_upd += 1

    con.commit()
    con.close()
    print(f"done trades_updated={upd} positions_entry_filled={p_upd} skipped={skip}", flush=True)

if __name__ == "__main__":
    main()
