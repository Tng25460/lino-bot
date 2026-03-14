#!/usr/bin/env python3
"""
cleanup_dead_positions.py — Nettoyage safe des positions mortes
================================================================

Identifie les positions OPEN dans trades.sqlite dont le solde on-chain
est zero (dust / untradable / deja vendues) et les marque CLOSED.

MODE DRY_RUN=1 (defaut) : affiche ce qui serait ferme, ne modifie rien.
MODE DRY_RUN=0 : ferme reellement les positions mortes.

Usage:
  # Diagnostic seul (dry run)
  python scripts/cleanup_dead_positions.py

  # Nettoyage reel
  DRY_RUN=0 python scripts/cleanup_dead_positions.py

  # Avec seuil de poussiere personnalise (en tokens)
  DUST_THRESHOLD=100 python scripts/cleanup_dead_positions.py

Env vars:
  TRADES_DB_PATH / DB_PATH  : chemin vers trades.sqlite
  RPC_HTTP                  : endpoint RPC Solana
  WALLET_PUBKEY / TRADER_USER_PUBLIC_KEY : pubkey du wallet
  DRY_RUN                   : 1=diagnostic, 0=execute (default: 1)
  DUST_THRESHOLD            : seuil de poussiere en tokens (default: 0.0)
  BATCH_SLEEP               : sleep entre appels RPC en secondes (default: 0.2)

Securite:
  - Ne DELETE jamais de lignes (UPDATE status seulement)
  - close_reason = 'cleanup_dead_zero_balance' (tracable)
  - Fail-open: si un RPC echoue, on skip la position
  - Log complet avant chaque action
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time


def _load_env_file(path: str = "state/live.env") -> int:
    """
    Charge un fichier .env sans dependance externe (pas de python-dotenv).
    Format supporte: export KEY="value" / KEY=value / KEY='value'
    Ne surcharge PAS les variables deja definies (os.environ a priorite).
    Retourne le nombre de variables chargees.
    """
    loaded = 0
    try:
        if not os.path.exists(path):
            return 0
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Supprimer 'export ' prefix
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                # Supprimer quotes
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                # Ne pas surcharger
                if key and key not in os.environ:
                    os.environ[key] = val
                    loaded += 1
    except Exception:
        pass
    return loaded


def main():
    # --- Auto-load state/live.env (sans python-dotenv) ---
    _n = _load_env_file("state/live.env")
    if _n > 0:
        print(f"  📄 Loaded {_n} vars from state/live.env")

    # --- Config ---
    DB = os.getenv("TRADES_DB_PATH", os.getenv("DB_PATH", "state/trades.sqlite"))
    RPC = os.getenv(
        "RPC_HTTP",
        os.getenv("SOLANA_RPC_HTTP",
        os.getenv("SOLANA_RPC_URL",
        os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")))
    )
    WALLET = (
        os.getenv("WALLET_PUBKEY", "").strip()
        or os.getenv("TRADER_USER_PUBLIC_KEY", "").strip()
    )
    DRY_RUN = os.getenv("DRY_RUN", "1").strip().lower() not in ("0", "false", "no", "off")
    DUST = float(os.getenv("DUST_THRESHOLD", "0.0"))
    BATCH_SLEEP = float(os.getenv("BATCH_SLEEP", "0.2"))

    print("=" * 60)
    print("CLEANUP DEAD POSITIONS")
    print("=" * 60)
    print(f"  DB:             {DB}")
    print(f"  RPC:            {RPC[:50]}...")
    print(f"  WALLET:         {WALLET[:12]}..." if WALLET else "  WALLET:         ⚠️ MISSING")
    print(f"  DRY_RUN:        {DRY_RUN}")
    print(f"  DUST_THRESHOLD: {DUST}")
    print()

    if not WALLET:
        print("❌ WALLET_PUBKEY ou TRADER_USER_PUBLIC_KEY requis")
        sys.exit(1)

    if not os.path.exists(DB):
        print(f"❌ DB introuvable: {DB}")
        sys.exit(1)

    # --- Load open positions (schema-safe) ---
    con = sqlite3.connect(DB, timeout=5.0)
    con.row_factory = sqlite3.Row
    # Découvrir les colonnes disponibles pour éviter "no such column"
    _cols_info = con.execute("PRAGMA table_info(positions)").fetchall()
    _col_names = {row[1] for row in _cols_info}
    # Construire une requête adaptée au schéma réel
    _select_cols = ["mint", "status"]
    for _c in ("id", "symbol", "qty_token", "entry_price", "entry_ts", "size_sol"):
        if _c in _col_names:
            _select_cols.append(_c)
    _select = ", ".join(_select_cols)
    rows = con.execute(
        f"SELECT {_select} FROM positions WHERE status LIKE 'OPEN%' ORDER BY entry_ts ASC"
        if "entry_ts" in _col_names else
        f"SELECT {_select} FROM positions WHERE status LIKE 'OPEN%'"
    ).fetchall()
    print(f"📊 Positions OPEN: {len(rows)}")
    print(f"   Colonnes détectées: {sorted(_col_names)}")
    print()

    if not rows:
        print("✅ Aucune position ouverte")
        con.close()
        return

    # --- Check each position on-chain ---
    import requests

    dead = []
    alive = []
    errors = []

    for i, row in enumerate(rows):
        mint = row["mint"]
        pos_id = row["id"] if "id" in _col_names else i
        symbol = (row["symbol"] if "symbol" in _col_names else None) or "?"
        qty_db = float((row["qty_token"] if "qty_token" in _col_names else None) or 0.0)

        # RPC: getTokenAccountsByOwner for this mint
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    WALLET,
                    {"mint": mint},
                    {"encoding": "jsonParsed", "commitment": "processed"}
                ]
            }
            r = requests.post(RPC, json=payload, timeout=10.0)
            if r.status_code != 200:
                errors.append((pos_id, mint, symbol, f"http_{r.status_code}"))
                print(f"  ⚠️ [{i+1}/{len(rows)}] {symbol} ({mint[:8]}…) RPC http={r.status_code}")
                time.sleep(BATCH_SLEEP)
                continue

            data = r.json()
            if "error" in data:
                errors.append((pos_id, mint, symbol, str(data["error"])[:80]))
                print(f"  ⚠️ [{i+1}/{len(rows)}] {symbol} ({mint[:8]}…) RPC error")
                time.sleep(BATCH_SLEEP)
                continue

            accounts = data.get("result", {}).get("value", [])
            total_balance = 0.0
            for acc in accounts:
                try:
                    info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                    amt = info.get("tokenAmount", {})
                    total_balance += float(amt.get("uiAmount", 0) or 0)
                except Exception:
                    pass

            if total_balance <= DUST:
                dead.append({
                    "id": pos_id,
                    "mint": mint,
                    "symbol": symbol,
                    "qty_db": qty_db,
                    "balance_onchain": total_balance,
                    "entry_ts": row["entry_ts"] if "entry_ts" in _col_names else 0,
                    "size_sol": float((row["size_sol"] if "size_sol" in _col_names else None) or 0),
                })
                age_h = (int(time.time()) - int(row["entry_ts"] or 0)) / 3600 if row["entry_ts"] else 0
                print(f"  💀 [{i+1}/{len(rows)}] {symbol:>10} ({mint[:8]}…) balance={total_balance:.6f} qty_db={qty_db:.2f} age={age_h:.0f}h → DEAD")
            else:
                alive.append((pos_id, mint, symbol, total_balance))
                print(f"  ✅ [{i+1}/{len(rows)}] {symbol:>10} ({mint[:8]}…) balance={total_balance:.6f}")

        except Exception as e:
            errors.append((pos_id, mint, symbol, str(e)[:80]))
            print(f"  ⚠️ [{i+1}/{len(rows)}] {symbol} ({mint[:8]}…) exception: {e}")

        time.sleep(BATCH_SLEEP)

    # --- Summary ---
    print()
    print("=" * 60)
    print(f"📊 RÉSUMÉ:")
    print(f"  Alive (balance > 0):  {len(alive)}")
    print(f"  Dead (balance = 0):   {len(dead)}")
    print(f"  Errors (RPC failed):  {len(errors)}")
    print()

    if not dead:
        print("✅ Aucune position morte détectée")
        con.close()
        return

    # --- Apply or show ---
    if DRY_RUN:
        print("🔍 MODE DRY_RUN — Voici ce qui SERAIT fermé :")
        for d in dead:
            print(f"  → id={d['id']} {d['symbol']} ({d['mint'][:8]}…) "
                  f"balance={d['balance_onchain']:.6f} size_sol={d['size_sol']:.4f}")
        print()
        print("Pour exécuter le nettoyage :")
        print("  DRY_RUN=0 python scripts/cleanup_dead_positions.py")
    else:
        print("🧹 APPLICATION DU NETTOYAGE...")
        now_ts = int(time.time())
        closed_count = 0
        # Construire UPDATE adapté au schéma réel
        _upd_parts = ["status='CLOSED'"]
        _upd_params_tpl = []
        if "close_reason" in _col_names:
            _upd_parts.append("close_reason=?")
            _upd_params_tpl.append("cleanup_dead_zero_balance")
        if "close_ts" in _col_names:
            _upd_parts.append("close_ts=?")
            _upd_params_tpl.append(now_ts)
        if "close_price_usd" in _col_names:
            _upd_parts.append("close_price_usd=0.0")
        # Clé primaire : id ou mint selon schéma
        _pk_col = "id" if "id" in _col_names else "mint"
        _upd_sql = f"UPDATE positions SET {', '.join(_upd_parts)} WHERE {_pk_col}=? AND status LIKE 'OPEN%'"
        for d in dead:
            try:
                _params = list(_upd_params_tpl) + [d["id"] if _pk_col == "id" else d["mint"]]
                con.execute(_upd_sql, _params)
                closed_count += 1
                print(f"  ✅ CLOSED id={d['id']} {d['symbol']} ({d['mint'][:8]}…)")
            except Exception as e:
                print(f"  ❌ FAILED id={d['id']} {d['symbol']}: {e}")

        con.commit()
        print()
        print(f"✅ {closed_count}/{len(dead)} positions fermées (close_reason='cleanup_dead_zero_balance')")

    con.close()
    print()
    print("Vérification :")
    print(f"  sqlite3 {DB} \"SELECT COUNT(*) FROM positions WHERE status LIKE 'OPEN%'\"")
    print(f"  sqlite3 {DB} \"SELECT id,mint,symbol,close_reason FROM positions WHERE close_reason='cleanup_dead_zero_balance' ORDER BY close_ts DESC LIMIT 20\"")


if __name__ == "__main__":
    main()
