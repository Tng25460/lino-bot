from __future__ import annotations

import os

def _env_bool(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in ("1","true","yes","on")

def _env_float(name: str, default: float) -> float:
    try:
        return float((os.getenv(name, "") or "").strip() or default)
    except Exception:
        return float(default)

def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name, "") or "").strip() or default)
    except Exception:
        return int(default)

def _env_str(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or default).strip()

# --- MODE / RPC ---
MODE = _env_str("MODE", "PAPER").upper()  # PAPER / REAL
RPC_URL = _env_str("RPC_URL", _env_str("RPC_HTTP", "https://api.mainnet-beta.solana.com"))

# --- Scanner ---
SCAN_INTERVAL_SECONDS = _env_int("SCAN_INTERVAL_SECONDS", 25)
NEW_LISTING_LIMIT = _env_int("NEW_LISTING_LIMIT", 5)
GLOBAL_RPS = _env_float("GLOBAL_RPS", 0.2)
MAX_CONCURRENCY = _env_int("MAX_CONCURRENCY", 1)

# --- Buy filters ---
BUY_AMOUNT_SOL = _env_float("BUY_AMOUNT_SOL", _env_float("TRADER_SOL_AMOUNT", 0.01))
BUY_COOLDOWN_SECONDS = _env_float("BUY_COOLDOWN_SECONDS", 0.0)
BUY_COOLDOWN_PER_MINT_SECONDS = _env_float("BUY_COOLDOWN_PER_MINT_SECONDS", 900.0)
BUY_COOLDOWN_AFTER_SELL_SECONDS = _env_float("BUY_COOLDOWN_AFTER_SELL_SECONDS", 900.0)
MAX_OPEN_POSITIONS = _env_int("MAX_OPEN_POSITIONS", 2)

MIN_PRICE_CHANGE_5M = _env_float("MIN_PRICE_CHANGE_5M", 6.0)
MIN_VOLUME_5M = _env_float("MIN_VOLUME_5M", 3000.0)
MIN_BUY_SELL_RATIO = _env_float("MIN_BUY_SELL_RATIO", 1.2)

# --- Anti-rug thresholds (defaults strict) ---
RISK_REQUIRE_RENOUNCED = _env_bool("RISK_REQUIRE_RENOUNCED", "1")
RISK_BLOCK_TOKEN_2022 = _env_bool("RISK_BLOCK_TOKEN_2022", "1")
RISK_MAX_TOP1_PCT = _env_float("RISK_MAX_TOP1_PCT", 0.25)   # 25%
RISK_MAX_TOP10_PCT = _env_float("RISK_MAX_TOP10_PCT", 0.60) # 60%
RISK_CACHE_TTL_SEC = _env_int("RISK_CACHE_TTL_SEC", 900)    # 15min

# --- Liquidity / marketcap (used by risk_checks.py) ---
MIN_LIQUIDITY_USD = _env_float("MIN_LIQUIDITY_USD", 15000.0)
MAX_MARKET_CAP_USD = _env_float("MAX_MARKET_CAP_USD", 300000.0)
