import os, sqlite3, time, math

MAX_IMPACT_PCT = float(os.getenv("BRAIN_MAX_IMPACT_PCT", "0.12"))
MAX_ROUTE_LEN   = int(os.getenv("BRAIN_MAX_ROUTE_LEN", "2"))

DB = os.getenv("BRAIN_DB", "state/brain.sqlite")
MIN_DT = int(os.getenv("BRAIN_SCORE_MIN_DT", "20"))
MAX_DT = int(os.getenv("BRAIN_SCORE_MAX_DT", "900"))

def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    now = int(time.time())

    # latest obs per mint
    latest = con.execute("""
      SELECT o.*
      FROM token_observations o
      JOIN (SELECT mint, MAX(ts) AS ts_max FROM token_observations GROUP BY mint) x
        ON x.mint=o.mint AND x.ts_max=o.ts
    """).fetchall()

    updated = 0
    for o2 in latest:
        mint = o2["mint"]
        ts2 = int(o2["ts"])
        p2  = float(o2["price"] or 0.0)
        if p2 <= 0: 
            continue

        prev = con.execute(
            "SELECT * FROM token_observations WHERE mint=? AND ts < ? ORDER BY ts DESC LIMIT 1",
            (mint, ts2)
        ).fetchone()
        if not prev:
            continue

        ts1 = int(prev["ts"])
        dt = ts2 - ts1
        if dt < MIN_DT or dt > MAX_DT:
            continue

        p1 = float(prev["price"] or 0.0)
        if p1 <= 0:
            continue

        ret = (p2/p1) - 1.0

        # optional extras if present
        def f(col):
            try:
                v = o2[col]
                return float(v) if v is not None else 0.0
            except Exception:
                return 0.0

        vol5 = f("vol_5m")
        tx5  = f("txns_5m")
        liq  = f("liq_usd")
        imp  = f("price_impact_pct")
        rlen = f("route_len")

        # gates: avoid thin routes
        if imp is not None and imp > MAX_IMPACT_PCT:
            # optional: debug gate
            print(f"[gate] skip mint={mint} imp={imp:.4g} > {MAX_IMPACT_PCT}", flush=True)
            continue
        if rlen is not None and rlen > MAX_ROUTE_LEN:
            print(f"[gate] skip mint={mint} rlen={rlen} > {MAX_ROUTE_LEN}", flush=True)
            continue

        score = 0.0
        score += 100.0 * ret
        score += 0.02 * math.log1p(max(0.0, vol5))
        score += 0.15 * math.log1p(max(0.0, tx5))
        score += 0.01 * math.log1p(max(0.0, liq))
        # prefer low price impact + short routes
        score += (-0.5) * max(0.0, imp)
        score += (-0.05) * max(0.0, rlen)

        reason = f"dt={dt}s ret={ret:+.3%} vol5={vol5:.3g} tx5={tx5:.3g} liq={liq:.3g} imp={imp:.4g} rlen={rlen:.0f}"

        con.execute("""
          INSERT INTO token_scores_v1(mint, ts, score, reason)
          VALUES(?,?,?,?)
          ON CONFLICT(mint) DO UPDATE SET
            ts=excluded.ts,
            score=excluded.score,
            reason=excluded.reason
        """, (mint, now, float(score), reason))
        updated += 1

    con.commit()
    print(f"[score_v1] updated={updated}")

    rows = con.execute("SELECT mint, score, ts, reason FROM token_scores_v1 ORDER BY score DESC LIMIT 20").fetchall()
    for r in rows:
        print(f"{r['mint']} score={r['score']:.4f} ts={r['ts']} {r['reason']}")

    con.close()

if __name__ == "__main__":
    main()
