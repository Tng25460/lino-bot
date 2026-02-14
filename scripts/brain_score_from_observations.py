import os, sqlite3, time, math

DB = os.getenv("BRAIN_DB", "state/brain.sqlite")
MIN_DT = int(os.getenv("BRAIN_SCORE_MIN_DT", "20"))     # sec
MAX_DT = int(os.getenv("BRAIN_SCORE_MAX_DT", "900"))    # sec

def table_cols(con, table):
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}

def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    obs_cols = table_cols(con, "token_observations")
    if not {"mint","ts","price"} <= obs_cols:
        raise SystemExit(f"token_observations missing required cols; have={sorted(list(obs_cols))}")

    score_cols = table_cols(con, "token_scores")
    # token_scores expected but may differ; we handle common names
    # We'll try: mint, ts, score, reason
    want = {"mint","ts","score","reason"}
    if not want <= score_cols:
        print(f"[score] token_scores cols={sorted(list(score_cols))} (need at least {sorted(list(want))})")
        # If schema differs, still try best-effort insert with available cols.
    now = int(time.time())

    # build last two observations per mint
    q = """
    SELECT o.*
    FROM token_observations o
    JOIN (
      SELECT mint, MAX(ts) AS ts_max FROM token_observations GROUP BY mint
    ) x ON x.mint=o.mint AND x.ts_max=o.ts
    """
    latest = {r["mint"]: r for r in con.execute(q).fetchall()}

    # previous obs within window
    updated = 0
    for mint, o2 in latest.items():
        ts2 = int(o2["ts"])
        p2  = float(o2["price"] or 0.0)
        if p2 <= 0: 
            continue

        # pick previous obs before ts2
        prev = con.execute(
            "SELECT * FROM token_observations WHERE mint=? AND ts < ? ORDER BY ts DESC LIMIT 1",
            (mint, ts2)
        ).fetchone()
        if not prev:
            continue

        ts1 = int(prev["ts"])
        dt  = ts2 - ts1
        if dt < MIN_DT or dt > MAX_DT:
            continue
        p1  = float(prev["price"] or 0.0)
        if p1 <= 0:
            continue

        ret = (p2/p1) - 1.0  # simple return
        # extras
        vol5 = float(o2["vol_5m"]) if "vol_5m" in obs_cols and o2["vol_5m"] is not None else 0.0
        tx5  = float(o2["txns_5m"]) if "txns_5m" in obs_cols and o2["txns_5m"] is not None else 0.0
        liq  = float(o2["liq_usd"]) if "liq_usd" in obs_cols and o2["liq_usd"] is not None else 0.0

        # score: momentum + light liquidity/flow bonus
        score = 0.0
        score += 100.0 * ret
        score += 0.02 * math.log1p(max(0.0, vol5))
        score += 0.15 * math.log1p(max(0.0, tx5))
        score += 0.01 * math.log1p(max(0.0, liq))

        reason = f"dt={dt}s ret={ret:+.3%} vol5={vol5:.3g} tx5={tx5:.3g} liq={liq:.3g}"

        # upsert into token_scores (supports common schema)
        cols = []
        vals = []
        if "mint" in score_cols: cols.append("mint"); vals.append(mint)
        if "ts" in score_cols: cols.append("ts"); vals.append(now)
        if "score" in score_cols: cols.append("score"); vals.append(float(score))
        if "reason" in score_cols: cols.append("reason"); vals.append(reason)

        if not cols:
            continue

        # if token_scores has unique mint, we can UPSERT; otherwise plain insert
        # try upsert on mint
        try:
            con.execute(
                f"INSERT INTO token_scores ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))}) "
                f"ON CONFLICT(mint) DO UPDATE SET "
                + ",".join([f"{c}=excluded.{c}" for c in cols if c != "mint"]),
                vals
            )
        except sqlite3.OperationalError:
            con.execute(
                f"INSERT INTO token_scores ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",
                vals
            )

        updated += 1

    con.commit()
    print(f"[score] updated={updated}")
    # show top
    try:
        rows = con.execute("SELECT mint, score, ts, reason FROM token_scores ORDER BY score DESC LIMIT 15").fetchall()
        for r in rows:
            print(f"{r['mint']} score={r['score']:.4f} ts={r['ts']} {r['reason']}")
    except Exception as e:
        print(f"[score] top15 print failed: {e}")

    con.close()

if __name__ == "__main__":
    main()
