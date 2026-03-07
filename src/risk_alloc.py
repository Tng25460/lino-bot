import os
import sqlite3

def is_pump(mint: str) -> bool:
    try:
        return str(mint).endswith("pump")
    except:
        return False

def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except:
        return default

def env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except:
        return default

def count_open_by_profile(db_path="state/trades.sqlite"):
    pump = 0
    normal = 0
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        rows = cur.execute(
            "SELECT mint FROM positions WHERE lower(coalesce(status,''))='open'"
        ).fetchall()
        for (m,) in rows:
            if is_pump(m):
                pump += 1
            else:
                normal += 1
        con.close()
    except:
        pass
    return pump, normal

def apply_profile_limits(mint: str):
    pump_open, normal_open = count_open_by_profile()

    max_pump = env_int("MAX_PUMP_POSITIONS", 20)
    max_norm = env_int("MAX_NORMAL_POSITIONS", 20)

    if is_pump(mint):
        if pump_open >= max_pump:
            return False, f"pump_open={pump_open} >= MAX_PUMP_POSITIONS={max_pump}"
        os.environ["BUY_AMOUNT_SOL"] = str(env_float("BUY_AMOUNT_SOL_PUMP", 0.003))
        os.environ["COOLDOWN_SEC"] = str(env_int("COOLDOWN_PUMP_SEC", 600))
    else:
        if normal_open >= max_norm:
            return False, f"normal_open={normal_open} >= MAX_NORMAL_POSITIONS={max_norm}"
        os.environ["BUY_AMOUNT_SOL"] = str(env_float("BUY_AMOUNT_SOL_NORMAL", 0.003))
        os.environ["COOLDOWN_SEC"] = str(env_int("COOLDOWN_NORMAL_SEC", 1800))

    return True, "ok"
