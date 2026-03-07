import os, sqlite3, subprocess, sys, time

DB_PATH = os.getenv("DB_PATH", "state/trades.sqlite")
BATCH = int(os.getenv("BATCH", "2") or 2)
SLEEP_S = float(os.getenv("SLEEP_S", "2.5") or 2.5)
SELL_DRY_RUN = str(os.getenv("SELL_DRY_RUN", "1")).lower() in ("1","true","yes","y")

def open_positions(conn):
    cur = conn.cursor()
    # status variants: 'OPEN' default, sometimes 'open'
    rows = cur.execute("""
        SELECT mint, qty_token
        FROM positions
        WHERE lower(coalesce(status,''))='open'
        ORDER BY entry_ts ASC
    """).fetchall()
    out = []
    for mint, qty in rows:
        try:
            qty = float(qty or 0.0)
        except Exception:
            qty = 0.0
        out.append((mint, qty))
    return out

def close_db(conn, mint, reason):
    cur = conn.cursor()
    cur.execute("""
        UPDATE positions
        SET status='closed', close_reason=?, close_ts=strftime('%s','now')
        WHERE mint=? AND lower(coalesce(status,''))='open'
    """, (reason, mint))
    conn.commit()

def run_sell(mint, ui_amount, reason):
    cmd = [
        sys.executable, "-u", "src/sell_exec_wrap.py",
        "--mint", str(mint),
        "--ui", str(ui_amount),
        "--reason", str(reason),
    ]
    env = os.environ.copy()
    # on force le mode dry_run côté wrap si demandé
    if SELL_DRY_RUN:
        env["SELL_DRY_RUN"] = "1"
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    out_all = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    lo = out_all.lower()
    rc = int(p.returncode or 0)

    # mapping markers (aligné avec ton sell_engine actuel)
    if "__TOKEN_NOT_TRADABLE__" in out_all or rc == 45:
        return "__NOT_TRADABLE__", out_all
    if "__JUP_HTTP_429__" in out_all or rc == 44 or "http=429" in lo or "too many requests" in lo:
        return "__JUP_HTTP_429__", out_all
    if "__ROUTE_FAIL__" in out_all or rc == 42 or "route_fail" in lo or "0x1788" in lo:
        return "__ROUTE_FAIL__", out_all
    if "__JUP_INSUFFICIENT_FUNDS__" in out_all or rc == 43 or "insufficient" in lo:
        return "__INSUFFICIENT__", out_all
    if "__DUST__" in out_all or "dust_untradeable" in lo or ("bad request" in lo and "amount=1" in lo):
        return "__DUST__", out_all

    # txsig detect
    import re
    m = re.search(r"\btxsig=([1-9A-HJ-NP-Za-km-z]{40,})\b", out_all)
    if m:
        return m.group(1), out_all
    return "__FAIL__", out_all

def main():
    conn = sqlite3.connect(DB_PATH)
    ops = open_positions(conn)
    print(f"OPEN_POSITIONS={len(ops)} BATCH={BATCH} SELL_DRY_RUN={int(SELL_DRY_RUN)}", flush=True)
    done = 0

    for mint, qty in ops:
        if done >= BATCH:
            break
        if not mint:
            continue
        if qty <= 0:
            # rien en DB => on ferme proprement (cas fréquent après resync raté)
            print(f"[CLOSE_DB] mint={mint} qty_token={qty} reason=qty_zero_db", flush=True)
            close_db(conn, mint, "qty_zero_db")
            done += 1
            continue

        print(f"[TRY_SELL] mint={mint} ui={qty}", flush=True)
        marker, out = run_sell(mint, qty, "liquidate_batch")
        print(f"[RESULT] mint={mint} marker={marker}", flush=True)

        if marker in ("__DUST__", "__NOT_TRADABLE__"):
            reason = "dust_untradeable" if marker == "__DUST__" else "token_not_tradable"
            print(f"[CLOSE_DB] mint={mint} reason={reason}", flush=True)
            close_db(conn, mint, reason)
            done += 1
        elif marker.startswith("__"):
            # 429 / route_fail / insufficient / fail -> on laisse OPEN
            done += 1
        else:
            # txsig -> on laisse le moteur gérer la fermeture après confirmation/prix;
            # on compte quand même comme traité pour batch.
            done += 1

        time.sleep(SLEEP_S)

    conn.close()
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
