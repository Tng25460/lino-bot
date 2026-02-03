import os, sqlite3, time
from flask import Flask, render_template_string

DB_PATH = os.getenv("DASH_DB", "state/trades.sqlite")
HOST = os.getenv("DASH_HOST", "0.0.0.0")
PORT = int(os.getenv("DASH_PORT", "5051"))
REFRESH = int(os.getenv("DASH_REFRESH_SEC", "10"))

app = Flask(__name__)

HTML = """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Lino Dashboard (SQLite)</title>
  <meta http-equiv="refresh" content="{{ refresh }}">
  <style>
    body{font-family:Arial;background:#050816;color:#f5f5f5;margin:0}
    .wrap{width:95%;margin:20px auto}
    h1{margin:0 0 10px 0;text-align:center}
    .meta{color:#9ca3af;text-align:center;margin-bottom:15px}
    table{width:100%;border-collapse:collapse}
    th,td{padding:8px 10px;border-bottom:1px solid #333;text-align:center}
    th{background:#111827}
    tr:nth-child(even){background:#0b1120}
    tr:nth-child(odd){background:#020617}
    .pill{display:inline-block;padding:3px 7px;border-radius:999px;background:#111827;font-size:.85rem}
    .ok{background:#16a34a}.warn{background:#f97316}.bad{background:#ef4444}
  </style>
</head>
<body>
<div class="wrap">
  <h1>📊 Lino Dashboard (SQLite)</h1>
  <div class="meta">
    DB: <span class="pill">{{ db }}</span> • refresh {{ refresh }}s • now {{ now_h }}
  </div>

  {% if err %}
    <div class="pill bad">Erreur: {{ err }}</div>
  {% endif %}

  <h2>Open positions ({{ rows|length }})</h2>
  <table>
    <thead>
      <tr>
        <th>mint</th>
        <th>qty_token</th>
        <th>entry</th>
        <th>price</th>
        <th>pnl%</th>
        <th>tp1</th>
        <th>tp2</th>
        <th>age(min)</th>
        <th>close_reason</th>
      </tr>
    </thead>
    <tbody>
      {% for r in rows %}
      <tr>
        <td style="font-family:monospace">{{ r["mint"] }}</td>
        <td>{{ r["qty_token"] }}</td>
        <td>{{ r["entry_price"] }}</td>
        <td>{{ r["last_price"] }}</td>
        <td>
          {% if r["pnl_pct"] is none %}
            -
          {% else %}
            {% if r["pnl_pct"] >= 0 %}
              <span class="pill ok">{{ r["pnl_pct"] }}%</span>
            {% elif r["pnl_pct"] > -10 %}
              <span class="pill warn">{{ r["pnl_pct"] }}%</span>
            {% else %}
              <span class="pill bad">{{ r["pnl_pct"] }}%</span>
            {% endif %}
          {% endif %}
        </td>
        <td>{{ r["tp1_done"] }}</td>
        <td>{{ r["tp2_done"] }}</td>
        <td>{{ r["age_min"] }}</td>
        <td>{{ r["close_reason"] or "" }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
</body>
</html>
"""

def _fmt(x):
    if x is None: return None
    try:
        xf = float(x)
        # keep compact
        if abs(xf) >= 1:
            return round(xf, 6)
        return round(xf, 8)
    except Exception:
        return x

def load_open_positions():
    if not os.path.exists(DB_PATH):
        return [], f"DB not found: {DB_PATH}"

    err = None
    rows = []
    try:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # best-effort schema: assume positions table exists
        # we try common columns; if missing, we still render something.
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        if "positions" not in tables:
            return [], f"table 'positions' not found in {DB_PATH} (found: {sorted(tables)})"

        # detect columns
        cur.execute("PRAGMA table_info(positions)")
        cols = [r[1] for r in cur.fetchall()]
        have = set(cols)

        want = ["mint","qty_token","entry_price","tp1_done","tp2_done","opened_at","close_reason","last_price"]
        select_cols = [c for c in want if c in have]
        if "mint" not in have:
            return [], "positions table has no 'mint' column"

        q = f"SELECT {', '.join(select_cols) if select_cols else '*'} FROM positions WHERE (is_open=1 OR closed_at IS NULL)"
        cur.execute(q)
        fetched = cur.fetchall()

        now = time.time()
        for r in fetched:
            d = dict(r)
            mint = d.get("mint")
            qty = d.get("qty_token")
            entry = d.get("entry_price")
            price = d.get("last_price")
            opened = d.get("opened_at")
            tp1 = d.get("tp1_done", 0)
            tp2 = d.get("tp2_done", 0)
            cr = d.get("close_reason")

            pnl = None
            try:
                if entry is not None and price is not None and float(entry) > 0:
                    pnl = (float(price)/float(entry) - 1.0) * 100.0
            except Exception:
                pnl = None

            age_min = None
            try:
                if opened is not None:
                    age_min = round(max(0.0, (now - float(opened))/60.0), 1)
            except Exception:
                age_min = None

            rows.append({
                "mint": mint,
                "qty_token": _fmt(qty),
                "entry_price": _fmt(entry),
                "last_price": _fmt(price),
                "pnl_pct": None if pnl is None else round(pnl, 2),
                "tp1_done": tp1,
                "tp2_done": tp2,
                "age_min": age_min if age_min is not None else "-",
                "close_reason": cr,
            })

        con.close()
    except Exception as e:
        err = str(e)

    return rows, err

@app.route("/")
def home():
    rows, err = load_open_positions()
    now_h = time.strftime("%Y-%m-%d %H:%M:%S")
    return render_template_string(HTML, rows=rows, err=err, db=DB_PATH, refresh=REFRESH, now_h=now_h)

if __name__ == "__main__":
    print(f"[DashboardSQLite] http://{HOST}:{PORT}  db={DB_PATH}")
    app.run(host=HOST, port=PORT, debug=False)
