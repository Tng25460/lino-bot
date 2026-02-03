import os, sqlite3, time, math

DB_PATH = os.getenv("BRAIN_DB", "state/brain.sqlite")

def _clamp(x, a, b):
    return a if x < a else b if x > b else x

def load_token_stats():
    if not os.path.exists(DB_PATH):
        return {}
    con = sqlite3.connect(DB_PATH)
    try:
        rows = con.execute("SELECT token_address, n_events, usd_net, last_seen FROM token_stats;").fetchall()
    finally:
        con.close()
    d = {}
    for token, n_events, usd_net, last_seen in rows:
        d[str(token)] = {
            "n_events": float(n_events or 0),
            "usd_net": float(usd_net or 0.0),
            "last_seen": int(last_seen or 0),
        }
    return d

def history_score(mint: str, stats_map: dict) -> float:
    s = stats_map.get(str(mint))
    if not s:
        return 0.0

    n_events = s["n_events"]
    usd_net  = s["usd_net"]
    last_seen = s["last_seen"]

    # activity: log scale (0..~10)
    activity = math.log1p(n_events)

    # pnl-ish: compress (positive good, negative bad) into [-20..+20]
    pnl = _clamp(usd_net / 50.0, -20.0, 20.0)

    # recency: last_seen within 7 days gives up to +5
    now = int(time.time())
    age = max(0, now - int(last_seen))
    rec = 5.0 * _clamp(1.0 - (age / (7*24*3600)), 0.0, 1.0)

    # final
    return float(2.5*activity + pnl + rec)
