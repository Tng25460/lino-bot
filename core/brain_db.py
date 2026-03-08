"""
PHASE4_P4.1: Schema brain.sqlite elite + helpers d'acces.

Fondation de toute la couche Brain/Intelligence adaptive.
Toutes les tables utilisent CREATE TABLE IF NOT EXISTS → zero risque.
Les tables existantes (mint_hist, mint_stats, mint_scores, token_scores)
ne sont PAS modifiees — on cree de nouvelles tables a cote.

Tables creees:
  - mint_memory      : historique complet par mint (win_rate, pnl, drawdown, fails, etc.)
  - dev_memory       : historique par createur/deployer (rugs, pnl, blacklist)
  - regime_snapshots : snapshots reguliers du regime de marche
  - risk_state       : etat persistant du risk engine (budget jour, circuit breaker)
  - decision_log     : trace de chaque decision BUY/REJECT avec score breakdown
  - session_stats    : resume par session de trading
"""
from __future__ import annotations
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

BRAIN_DB_PATH = os.getenv("BRAIN_DB_PATH", os.getenv("BRAIN_DB", "state/brain.sqlite"))

# ============================================================
# Schema SQL
# ============================================================
_SCHEMA_ELITE = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- --------------------------------------------------------
-- mint_memory: historique complet par mint
-- Remplace/complete mint_hist avec des champs beaucoup plus riches
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS mint_memory (
    mint             TEXT PRIMARY KEY,
    symbol           TEXT DEFAULT '',
    profile          TEXT DEFAULT '',          -- PUMP / NORMAL / UNKNOWN
    source           TEXT DEFAULT '',          -- pump.fun / raydium / orca / ...
    -- compteurs de trades
    n_trades         INTEGER DEFAULT 0,
    n_closed         INTEGER DEFAULT 0,
    n_wins           INTEGER DEFAULT 0,
    n_losses         INTEGER DEFAULT 0,
    win_rate         REAL    DEFAULT 0.0,
    -- PnL
    avg_pnl          REAL    DEFAULT 0.0,
    best_pnl         REAL    DEFAULT 0.0,
    worst_pnl        REAL    DEFAULT 0.0,
    total_pnl        REAL    DEFAULT 0.0,
    max_drawdown     REAL    DEFAULT 0.0,      -- pire perte cumulee
    -- durees
    avg_hold_sec     REAL    DEFAULT 0.0,
    min_hold_sec     REAL    DEFAULT 0.0,
    max_hold_sec     REAL    DEFAULT 0.0,
    -- exits
    tp1_count        INTEGER DEFAULT 0,
    tp2_count        INTEGER DEFAULT 0,
    sl_count         INTEGER DEFAULT 0,
    trail_stop_count INTEGER DEFAULT 0,
    time_stop_count  INTEGER DEFAULT 0,
    -- echecs et incidents
    sell_fail_count  INTEGER DEFAULT 0,        -- tentatives de sell echouees
    route_fail_count INTEGER DEFAULT 0,        -- no route / not tradable
    rug_block_count  INTEGER DEFAULT 0,        -- antirug blocks
    rpc_429_count    INTEGER DEFAULT 0,        -- 429 rate limit
    -- timestamps
    first_trade_ts   INTEGER DEFAULT 0,
    last_trade_ts    INTEGER DEFAULT 0,
    last_close_ts    INTEGER DEFAULT 0,
    last_close_reason TEXT   DEFAULT '',
    -- meta
    tags             TEXT    DEFAULT '[]',      -- JSON array de tags
    updated_ts       INTEGER DEFAULT 0
);

-- --------------------------------------------------------
-- dev_memory: historique par createur / deployer
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS dev_memory (
    dev_address      TEXT PRIMARY KEY,
    -- compteurs
    n_tokens         INTEGER DEFAULT 0,        -- total tokens lances par ce dev
    n_rugged         INTEGER DEFAULT 0,        -- tokens qui ont rug
    n_traded         INTEGER DEFAULT 0,        -- tokens qu'on a trades
    n_profitable     INTEGER DEFAULT 0,        -- trades profitables de ce dev
    -- PnL
    avg_pnl          REAL    DEFAULT 0.0,
    worst_pnl        REAL    DEFAULT 0.0,
    best_pnl         REAL    DEFAULT 0.0,
    total_pnl        REAL    DEFAULT 0.0,
    -- blacklist
    blacklisted      INTEGER DEFAULT 0,        -- 0 = ok, 1 = blacklisted
    blacklist_reason TEXT    DEFAULT '',
    -- timestamps
    first_seen_ts    INTEGER DEFAULT 0,
    last_seen_ts     INTEGER DEFAULT 0,
    updated_ts       INTEGER DEFAULT 0
);

-- --------------------------------------------------------
-- regime_snapshots: etat du marche a un instant donne
-- Un snapshot est ecrit periodiquement (ex: chaque minute ou chaque cycle)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS regime_snapshots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               INTEGER NOT NULL,
    window_sec       INTEGER NOT NULL DEFAULT 300, -- fenetre d'observation (defaut 5 min)
    -- metriques dans la fenetre
    n_trades         INTEGER DEFAULT 0,
    n_wins           INTEGER DEFAULT 0,
    n_losses         INTEGER DEFAULT 0,
    win_rate         REAL    DEFAULT 0.0,
    avg_pnl          REAL    DEFAULT 0.0,
    n_buys           INTEGER DEFAULT 0,
    n_sells          INTEGER DEFAULT 0,
    n_429            INTEGER DEFAULT 0,
    n_route_fail     INTEGER DEFAULT 0,
    n_rug_block      INTEGER DEFAULT 0,
    avg_hold_sec     REAL    DEFAULT 0.0,
    -- regime detecte
    regime           TEXT    DEFAULT 'unknown', -- hot / cold / chop / rug / degraded / normal
    regime_score     REAL    DEFAULT 0.0,       -- -1.0 (tres mauvais) a +1.0 (tres bon)
    confidence       REAL    DEFAULT 0.0,       -- 0.0 a 1.0
    -- details
    details_json     TEXT    DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_regime_ts ON regime_snapshots(ts);

-- --------------------------------------------------------
-- risk_state: etat persistant du risk engine
-- Singleton (id=1 toujours). Reset chaque jour.
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS risk_state (
    id                      INTEGER PRIMARY KEY DEFAULT 1,
    day_date                TEXT    NOT NULL DEFAULT '',    -- YYYY-MM-DD
    -- compteurs du jour
    day_trades              INTEGER DEFAULT 0,
    day_wins                INTEGER DEFAULT 0,
    day_losses              INTEGER DEFAULT 0,
    day_pnl                 REAL    DEFAULT 0.0,
    day_max_pnl             REAL    DEFAULT 0.0,           -- high water mark du jour
    day_drawdown            REAL    DEFAULT 0.0,           -- pire drawdown intra-day
    -- series
    consecutive_losses      INTEGER DEFAULT 0,
    max_consecutive_losses  INTEGER DEFAULT 0,
    consecutive_wins        INTEGER DEFAULT 0,
    -- circuit breaker
    circuit_breaker_until   INTEGER DEFAULT 0,             -- unix ts, 0 = inactif
    circuit_breaker_reason  TEXT    DEFAULT '',
    -- sizing
    sizing_multiplier       REAL    DEFAULT 1.0,           -- 1.0 = normal, 0.5 = reduit
    -- budget
    risk_budget_used        REAL    DEFAULT 0.0,           -- 0.0 a 1.0 (fraction du budget jour)
    risk_budget_max         REAL    DEFAULT 0.0,           -- max SOL a risquer par jour
    -- meta
    last_update_ts          INTEGER DEFAULT 0
);

-- --------------------------------------------------------
-- decision_log: trace de chaque decision BUY/REJECT
-- Permet de comprendre pourquoi un token a ete achete ou rejete
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS decision_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               INTEGER NOT NULL,
    mint             TEXT    NOT NULL,
    symbol           TEXT    DEFAULT '',
    -- decision
    action           TEXT    NOT NULL,              -- BUY / REJECT / SKIP
    reason           TEXT    DEFAULT '',             -- raison principale
    -- score breakdown (chaque composante explicable)
    score_total      REAL    DEFAULT 0.0,
    score_market     REAL    DEFAULT 0.0,           -- qualite des metriques marche
    score_flow       REAL    DEFAULT 0.0,           -- volume / momentum
    score_history    REAL    DEFAULT 0.0,           -- historique mint dans brain
    score_dev        REAL    DEFAULT 0.0,           -- reputation du createur
    score_risk       REAL    DEFAULT 0.0,           -- risque estime (concentration, etc.)
    score_execution  REAL    DEFAULT 0.0,           -- qualite d'execution (route, 429, etc.)
    -- contexte
    regime           TEXT    DEFAULT '',             -- regime marche au moment de la decision
    sizing_sol       REAL    DEFAULT 0.0,           -- taille proposee en SOL
    profile          TEXT    DEFAULT '',             -- PUMP / NORMAL
    -- details complets
    details_json     TEXT    DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_decision_ts ON decision_log(ts);
CREATE INDEX IF NOT EXISTS idx_decision_mint ON decision_log(mint);

-- --------------------------------------------------------
-- session_stats: resume par session de trading
-- Une session = un run du bot (start → stop)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS session_stats (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_start_ts  INTEGER NOT NULL,
    session_end_ts    INTEGER DEFAULT 0,
    -- compteurs
    n_buy_attempts    INTEGER DEFAULT 0,
    n_buys            INTEGER DEFAULT 0,
    n_sells           INTEGER DEFAULT 0,
    n_tp1             INTEGER DEFAULT 0,
    n_tp2             INTEGER DEFAULT 0,
    n_sl              INTEGER DEFAULT 0,
    n_trail           INTEGER DEFAULT 0,
    n_time_stop       INTEGER DEFAULT 0,
    -- PnL
    total_pnl         REAL    DEFAULT 0.0,
    best_trade_pnl    REAL    DEFAULT 0.0,
    worst_trade_pnl   REAL    DEFAULT 0.0,
    avg_hold_sec      REAL    DEFAULT 0.0,
    -- incidents
    n_429             INTEGER DEFAULT 0,
    n_rug_blocked     INTEGER DEFAULT 0,
    n_sell_fail       INTEGER DEFAULT 0,
    -- contexte
    regime_dominant   TEXT    DEFAULT '',
    notes             TEXT    DEFAULT ''
);
"""


# ============================================================
# Connexion et initialisation
# ============================================================
def get_db_path() -> str:
    """Retourne le chemin vers brain.sqlite (env-aware)."""
    return os.getenv("BRAIN_DB_PATH", os.getenv("BRAIN_DB", "state/brain.sqlite"))


def connect(db_path: str = "") -> sqlite3.Connection:
    """Connexion WAL-mode a brain.sqlite."""
    path = db_path or get_db_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path, timeout=15)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.row_factory = sqlite3.Row
    return con


def init_elite_schema(db_path: str = "") -> None:
    """
    Cree toutes les tables elite si elles n'existent pas.
    Safe a appeler plusieurs fois (idempotent).
    """
    con = connect(db_path)
    con.executescript(_SCHEMA_ELITE)
    con.commit()
    con.close()


# ============================================================
# Helpers mint_memory
# ============================================================
def get_mint_memory(mint: str, db_path: str = "") -> Optional[Dict[str, Any]]:
    """Lit la memoire d'un mint. Retourne None si inconnu."""
    con = connect(db_path)
    row = con.execute("SELECT * FROM mint_memory WHERE mint=?", (mint,)).fetchone()
    con.close()
    if row is None:
        return None
    return dict(row)


def upsert_mint_memory(mint: str, data: Dict[str, Any], db_path: str = "") -> None:
    """Insert ou update la memoire d'un mint."""
    con = connect(db_path)
    data["mint"] = mint
    data["updated_ts"] = int(time.time())
    cols = list(data.keys())
    placeholders = ",".join(["?"] * len(cols))
    updates = ",".join([f"{c}=excluded.{c}" for c in cols if c != "mint"])
    sql = f"INSERT INTO mint_memory ({','.join(cols)}) VALUES ({placeholders}) ON CONFLICT(mint) DO UPDATE SET {updates}"
    con.execute(sql, [data[c] for c in cols])
    con.commit()
    con.close()


# ============================================================
# Helpers dev_memory
# ============================================================
def get_dev_memory(dev_address: str, db_path: str = "") -> Optional[Dict[str, Any]]:
    """Lit la memoire d'un dev. Retourne None si inconnu."""
    con = connect(db_path)
    row = con.execute("SELECT * FROM dev_memory WHERE dev_address=?", (dev_address,)).fetchone()
    con.close()
    if row is None:
        return None
    return dict(row)


def upsert_dev_memory(dev_address: str, data: Dict[str, Any], db_path: str = "") -> None:
    """Insert ou update la memoire d'un dev."""
    con = connect(db_path)
    data["dev_address"] = dev_address
    data["updated_ts"] = int(time.time())
    cols = list(data.keys())
    placeholders = ",".join(["?"] * len(cols))
    updates = ",".join([f"{c}=excluded.{c}" for c in cols if c != "dev_address"])
    sql = f"INSERT INTO dev_memory ({','.join(cols)}) VALUES ({placeholders}) ON CONFLICT(dev_address) DO UPDATE SET {updates}"
    con.execute(sql, [data[c] for c in cols])
    con.commit()
    con.close()


def is_dev_blacklisted(dev_address: str, db_path: str = "") -> bool:
    """Verifie si un dev est blackliste."""
    mem = get_dev_memory(dev_address, db_path)
    if mem is None:
        return False
    return bool(mem.get("blacklisted", 0))


# ============================================================
# Helpers regime_snapshots
# ============================================================
def insert_regime_snapshot(data: Dict[str, Any], db_path: str = "") -> None:
    """Insere un snapshot regime."""
    con = connect(db_path)
    data.setdefault("ts", int(time.time()))
    cols = [c for c in data.keys() if c != "id"]
    placeholders = ",".join(["?"] * len(cols))
    sql = f"INSERT INTO regime_snapshots ({','.join(cols)}) VALUES ({placeholders})"
    con.execute(sql, [data[c] for c in cols])
    con.commit()
    con.close()


def get_latest_regime(db_path: str = "") -> Optional[Dict[str, Any]]:
    """Retourne le dernier snapshot regime."""
    con = connect(db_path)
    row = con.execute("SELECT * FROM regime_snapshots ORDER BY ts DESC LIMIT 1").fetchone()
    con.close()
    if row is None:
        return None
    return dict(row)


# ============================================================
# Helpers risk_state
# ============================================================
def get_risk_state(db_path: str = "") -> Dict[str, Any]:
    """
    Lit l'etat risk (singleton id=1).
    Si le jour a change, reset les compteurs journaliers.
    """
    con = connect(db_path)
    row = con.execute("SELECT * FROM risk_state WHERE id=1").fetchone()
    if row is None:
        # Premiere utilisation: initialiser
        today = time.strftime("%Y-%m-%d")
        con.execute(
            "INSERT INTO risk_state (id, day_date, last_update_ts) VALUES (1, ?, ?)",
            (today, int(time.time())),
        )
        con.commit()
        row = con.execute("SELECT * FROM risk_state WHERE id=1").fetchone()

    state = dict(row)

    # Auto-reset si nouveau jour
    today = time.strftime("%Y-%m-%d")
    if state.get("day_date") != today:
        con.execute(
            """UPDATE risk_state SET
                day_date=?, day_trades=0, day_wins=0, day_losses=0,
                day_pnl=0.0, day_max_pnl=0.0, day_drawdown=0.0,
                consecutive_losses=0, max_consecutive_losses=0, consecutive_wins=0,
                circuit_breaker_until=0, circuit_breaker_reason='',
                sizing_multiplier=1.0, risk_budget_used=0.0,
                last_update_ts=?
            WHERE id=1""",
            (today, int(time.time())),
        )
        con.commit()
        row = con.execute("SELECT * FROM risk_state WHERE id=1").fetchone()
        state = dict(row)

    con.close()
    return state


def update_risk_state(updates: Dict[str, Any], db_path: str = "") -> None:
    """Met a jour l'etat risk (singleton id=1)."""
    con = connect(db_path)
    updates["last_update_ts"] = int(time.time())
    sets = ",".join([f"{k}=?" for k in updates.keys()])
    sql = f"UPDATE risk_state SET {sets} WHERE id=1"
    con.execute(sql, list(updates.values()))
    con.commit()
    con.close()


# ============================================================
# Helpers decision_log
# ============================================================
def log_decision(
    mint: str,
    action: str,
    reason: str = "",
    *,
    symbol: str = "",
    score_total: float = 0.0,
    score_market: float = 0.0,
    score_flow: float = 0.0,
    score_history: float = 0.0,
    score_dev: float = 0.0,
    score_risk: float = 0.0,
    score_execution: float = 0.0,
    regime: str = "",
    sizing_sol: float = 0.0,
    profile: str = "",
    details: Optional[Dict] = None,
    db_path: str = "",
) -> None:
    """Enregistre une decision BUY/REJECT/SKIP avec score breakdown."""
    import json

    con = connect(db_path)
    con.execute(
        """INSERT INTO decision_log
        (ts, mint, symbol, action, reason,
         score_total, score_market, score_flow, score_history, score_dev, score_risk, score_execution,
         regime, sizing_sol, profile, details_json)
        VALUES (?,?,?,?,?, ?,?,?,?,?,?,?, ?,?,?,?)""",
        (
            int(time.time()),
            mint,
            symbol,
            action,
            reason,
            score_total,
            score_market,
            score_flow,
            score_history,
            score_dev,
            score_risk,
            score_execution,
            regime,
            sizing_sol,
            profile,
            json.dumps(details or {}, ensure_ascii=False),
        ),
    )
    con.commit()
    con.close()


def get_recent_decisions(
    limit: int = 50, action: str = "", db_path: str = ""
) -> List[Dict[str, Any]]:
    """Retourne les dernieres decisions."""
    con = connect(db_path)
    if action:
        rows = con.execute(
            "SELECT * FROM decision_log WHERE action=? ORDER BY ts DESC LIMIT ?",
            (action, limit),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM decision_log ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    con.close()
    return [dict(r) for r in rows]


# ============================================================
# Helpers session_stats
# ============================================================
def start_session(db_path: str = "") -> int:
    """Demarre une nouvelle session. Retourne le session_id."""
    con = connect(db_path)
    cur = con.execute(
        "INSERT INTO session_stats (session_start_ts) VALUES (?)",
        (int(time.time()),),
    )
    session_id = cur.lastrowid
    con.commit()
    con.close()
    return session_id


def update_session(session_id: int, updates: Dict[str, Any], db_path: str = "") -> None:
    """Met a jour les stats d'une session."""
    con = connect(db_path)
    sets = ",".join([f"{k}=?" for k in updates.keys()])
    sql = f"UPDATE session_stats SET {sets} WHERE id=?"
    con.execute(sql, list(updates.values()) + [session_id])
    con.commit()
    con.close()


def end_session(session_id: int, db_path: str = "") -> None:
    """Ferme une session (met session_end_ts)."""
    con = connect(db_path)
    con.execute(
        "UPDATE session_stats SET session_end_ts=? WHERE id=?",
        (int(time.time()), session_id),
    )
    con.commit()
    con.close()


# ============================================================
# Initialisation auto
# ============================================================
def ensure_schema(db_path: str = "") -> None:
    """
    Appel safe pour s'assurer que le schema elite existe.
    A appeler au demarrage du bot (run_live.py ou trader_exec.py).
    Idempotent, peut etre appele 1000 fois sans effet.
    """
    try:
        init_elite_schema(db_path)
    except Exception as e:
        print(f"⚠️ brain_db.ensure_schema failed (non-fatal): {e}", flush=True)


# ============================================================
# CLI standalone
# ============================================================
if __name__ == "__main__":
    path = get_db_path()
    print(f"[BRAIN_DB] Initializing elite schema → {path}")
    init_elite_schema()
    con = connect()
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    con.close()
    print(f"[BRAIN_DB] Tables: {', '.join(tables)}")
    print("[BRAIN_DB] OK ✅")
