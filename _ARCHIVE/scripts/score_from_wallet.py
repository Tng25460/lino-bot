#!/usr/bin/env python3
import os, sqlite3, time, json, math

DB=os.getenv("BRAIN_DB","state/brain.sqlite")
OWNER=os.getenv("SELL_OWNER_PUBKEY","").strip()
OUT=os.getenv("READY_WALLET_OUT","state/ready_wallet_scored.jsonl")

SINCE_MIN=int(os.getenv("WALLET_SCORE_SINCE_MIN","240"))  # default 4h
MAX_MINTS=int(os.getenv("WALLET_SCORE_MAX_MINTS","200"))

def main():
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row

    since_ts=int(time.time())-SINCE_MIN*60
    args=[]
    where=["mint IS NOT NULL"]
    if OWNER:
        where.append("owner=?"); args.append(OWNER)
    where.append("ts>=?"); args.append(since_ts)
    w=" AND ".join(where)

    rows=con.execute(f"""
      SELECT mint,
             max(ts) last_ts,
             count(*) n,
             sum(CASE WHEN kind='swap' THEN 1 ELSE 0 END) n_swaps,
             sum(abs(COALESCE(sol_change,0))) sol_abs,
             sum(COALESCE(sol_change,0)) sol_net
      FROM wallet_events
      WHERE {w}
      GROUP BY mint
      ORDER BY last_ts DESC
      LIMIT ?
    """, args+[MAX_MINTS]).fetchall()

    now=int(time.time())
    out=[]
    for r in rows:
        mint=r["mint"]
        age_s=max(1, now-int(r["last_ts"]))
        age_h=age_s/3600.0
        n=int(r["n"] or 0)
        nsw=int(r["n_swaps"] or 0)
        sol_abs=float(r["sol_abs"] or 0.0)
        sol_net=float(r["sol_net"] or 0.0)

        # scoring (simple, deterministic)
        score = 0.0
        score += min(10.0, n * 0.5)
        score += min(15.0, nsw * 1.5)
        score += min(20.0, math.log10(1.0 + sol_abs*1000.0) * 5.0)  # boost if SOL moved
        score -= min(20.0, age_h * 2.0)  # decay with time

        out.append({
            "mint": mint,
            "score": round(score, 4),
            "last_ts": int(r["last_ts"]),
            "age_s": age_s,
            "n": n,
            "n_swaps": nsw,
            "sol_abs": round(sol_abs, 8),
            "sol_net": round(sol_net, 8),
            "source": "wallet_events",
        })

    out.sort(key=lambda x: x["score"], reverse=True)

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for o in out:
            f.write(json.dumps(o, separators=(",",":"))+"\n")

    print(f"[OK] wrote {len(out)} mints -> {OUT}")
    if out:
        print("[TOP5]")
        for o in out[:5]:
            print(" ", o["mint"], "score=", o["score"], "n=", o["n"], "swaps=", o["n_swaps"], "age_s=", o["age_s"])

if __name__=="__main__":
    main()
