import json
import os
from typing import List, Dict, Any

from flask import Flask, render_template_string
from config.settings import POSITIONS_FILE, TRAILING_SL_PCT

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Lino Dashboard - Moonshot Trailing</title>
    <meta http-equiv="refresh" content="10">
    <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #050816;
            color: #f5f5f5;
            margin: 0;
            padding: 0;
        }
        h1, h2 {
            text-align: center;
        }
        .container {
            width: 90%;
            margin: 20px auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }
        th, td {
            padding: 8px 10px;
            border-bottom: 1px solid #333;
            text-align: center;
        }
        th {
            background-color: #111827;
        }
        tr:nth-child(even) {
            background-color: #0b1120;
        }
        tr:nth-child(odd) {
            background-color: #020617;
        }
        .badge {
            padding: 3px 7px;
            border-radius: 5px;
            font-size: 0.8rem;
        }
        .badge-open {
            background-color: #16a34a;
        }
        .badge-paper {
            background-color: #3b82f6;
        }
        .badge-real {
            background-color: #f97316;
        }
        .footer {
            text-align: center;
            font-size: 0.8rem;
            color: #9ca3af;
            margin-top: 20px;
        }
        .pill {
            display: inline-block;
            padding: 3px 7px;
            border-radius: 999px;
            background-color: #111827;
            font-size: 0.8rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Lino Dashboard</h1>
        <h2>Mode Moonshot Trailing Only</h2>

        <p style="text-align:center;">
            Mode actuel :
            {% if mode == "PAPER" %}
                <span class="badge badge-paper">PAPER (simulation)</span>
            {% else %}
                <span class="badge badge-real">REAL (live)</span>
            {% endif %}
        </p>

        <p style="text-align:center;">
            Trailing stop : 
            <span class="pill">{{ trailing_pct * 100 | round(1) }}% sous le plus haut</span>
        </p>

        {% if positions %}
        <table>
            <thead>
                <tr>
                    <th>Token</th>
                    <th>Entry price</th>
                    <th>Highest price</th>
                    <th>Trailing stop line</th>
                    <th>Investi (SOL)</th>
                    <th>Age (min)</th>
                    <th>Statut</th>
                </tr>
            </thead>
            <tbody>
                {% for p in positions %}
                <tr>
                    <td style="font-family: monospace;">{{ p.token }}</td>
                    <td>{{ "%.8f"|format(p.entry_price) }}</td>
                    <td>{{ "%.8f"|format(p.highest_price) }}</td>
                    <td>{{ "%.8f"|format(p.stop_line) }}</td>
                    <td>{{ "%.3f"|format(p.amount_sol) }}</td>
                    <td>{{ "%.1f"|format(p.age_min) }}</td>
                    <td><span class="badge badge-open">OPEN</span></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p style="text-align:center; margin-top:30px;">
            Aucune position ouverte pour l'instant.
        </p>
        {% endif %}

        <div class="footer">
            Rafraîchissement automatique toutes les 10s •
            Source : {{ positions_file }}
        </div>
    </div>
</body>
</html>
"""


def load_positions() -> List[Dict[str, Any]]:
    """Lit le fichier positions.json et renvoie une liste de positions enrichies pour l'affichage."""
    if not os.path.exists(POSITIONS_FILE):
        return []

    try:
        with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        print(f"[Dashboard] Erreur lecture {POSITIONS_FILE}: {e}")
        return []

    if not isinstance(raw, list):
        return []

    import time

    now = time.time()
    enriched = []
    for pos in raw:
        try:
            token = pos.get("token", "?")
            entry = float(pos.get("entry_price", 0.0))
            highest = float(pos.get("highest_price", entry))
            amount_sol = float(pos.get("amount_sol", 0.0))
            ts = float(pos.get("timestamp", now))

            stop_line = highest * (1.0 - TRAILING_SL_PCT)
            age_min = max(0.0, (now - ts) / 60.0)

            enriched.append(
                {
                    "token": token,
                    "entry_price": entry,
                    "highest_price": highest,
                    "stop_line": stop_line,
                    "amount_sol": amount_sol,
                    "age_min": age_min,
                }
            )
        except Exception as e:
            print(f"[Dashboard] Erreur parsing position: {e}")
            continue

    return enriched


@app.route("/")
def dashboard():
    positions = load_positions()

    # MODE est stocké dans settings, on le lit directement
    try:
        from config.settings import MODE as CURRENT_MODE
    except Exception:
        CURRENT_MODE = "UNKNOWN"

    return render_template_string(
        HTML_TEMPLATE,
        positions=positions,
        positions_file=POSITIONS_FILE,
        trailing_pct=TRAILING_SL_PCT,
        mode=CURRENT_MODE,
    )


if __name__ == "__main__":
    app.run(debug=False)
