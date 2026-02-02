#!/usr/bin/env python3
import os, sqlite3, time
from collections import defaultdict

DB=os.getenv("BRAIN_DB","state/brain.sqlite")
OWNER=os.getenv("SELL_OWNER_PUBKEY","").strip()
LAST_N=int(os.getenv("WALLET_LAST_N","50"))
SINCE_MIN=int(os.getenv("WALLET_SINCE_MIN","0"))  # 0 = no filter

def ago(ts:int)->str:
    d=max(0,int(time.time())-int(ts))
    if d<60: return f"{d}s"
    if d<3600: return f"{d//60}m"
    if d<86400: return f"{d//3600}h"
    return f"{d//86400}d"

def main():
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row

    where=[]
    args=[]
    if OWNER:
        where.append("owner=?")
        args.append(OWNER)
    if SINCE_MIN>0:
        where.append("ts>=?")
        args.append(int(time.time())-SINCE_MIN*60)
    w=("WHERE " + " AND ".join(where)) if where else ""

    total=con.execute(f"SELECT count(*) c FROM wallet_events {w}", args).fetchone()["c"]
    print(f"[DB] {DB}")
    if OWNER: print(f"[OWNER] {OWNER}")
    print(f"[ROWS] {total}")

    # SOL stats
    sol = con.execute(f"""
      SELECT
        COALESCE(sum(sol_change),0) as sol_net,
        COALESCE(sum(fee_sol),0) as fee_sum,
        COALESCE(avg(fee_sol),0) as fee_avg
      FROM wallet_events {w}
    """, args).fetchone()
    print(f"[SOL] net={sol['sol_net']:.6f} fee_sum={sol['fee_sum']:.6f} fee_avg={sol['fee_avg']:.6f}")

    # Top mints by abs token amount moved
    rows = con.execute(f"""
      SELECT mint, count(*) n,
             COALESCE(sum(abs(amount)),0) vol_abs,
             COALESCE(sum(sol_change),0) sol_net
      FROM wallet_events {w} AND mint IS NOT NULL
      GROUP BY mint
      ORDER BY vol_abs DESC
      LIMIT 12
    """, args).fetchall() if w else con.execute("""
      SELECT mint, count(*) n,
             COALESCE(sum(abs(amount)),0) vol_abs,
             COALESCE(sum(sol_change),0) sol_net
      FROM wallet_events WHERE mint IS NOT NULL
      GROUP BY mint
      ORDER BY vol_abs DESC
      LIMIT 12
    """).fetchall()

    print("\n[TOP_MINTS]")
    if not rows:
        print("  (none)")
    else:
        for r in rows:
            print(f"  {r['mint']}  n={r['n']}  abs_amt={float(r['vol_abs']):.3f}  sol_net={float(r['sol_net']):.6f}")

    # Last events
    last = con.execute(f"""
      SELECT ts, kind, mint, amount, sol_change, fee_sol, signature
      FROM wallet_events {w}
      ORDER BY ts DESC
      LIMIT ?
    """, args+[LAST_N]).fetchall()

    print(f"\n[LAST_{LAST_N}]")
    for r in last:
        ts=int(r["ts"])
        kind=r["kind"] or "tx"
        mint=r["mint"] or "-"
        amt=r["amount"]
        solc=r["sol_change"]
        fee=r["fee_sol"]
        sig=r["signature"]
        s_amt = "-" if amt is None else f"{float(amt):.6f}"
        s_sol = "-" if solc is None else f"{float(solc):.6f}"
        s_fee = "-" if fee is None else f"{float(fee):.6f}"
        print(f"  {ago(ts):>4}  {kind:<5} mint={mint} amt={s_amt} sol={s_sol} fee={s_fee} sig={sig[:10]}...")

    con.close()

if __name__=="__main__":
    main()
