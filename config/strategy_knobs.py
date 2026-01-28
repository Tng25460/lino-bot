import os

def _f(name, default):
    try: return float(os.getenv(name, str(default)))
    except: return float(default)

def _i(name, default):
    try: return int(float(os.getenv(name, str(default))))
    except: return int(default)

# --- Universe / liquidity gates ---
MIN_LIQ_USD          = _f("MIN_LIQ_USD", 12000)     # évite pools trop petites
MIN_VOL5M_USD        = _f("MIN_VOL5M_USD", 2500)    # vrai intérêt récent
MIN_VOL1H_USD        = _f("MIN_VOL1H_USD", 12000)

# --- Momentum gates ---
MIN_CHG5M_PCT        = _f("MIN_CHG5M_PCT", 4.0)     # breakout récent
MAX_CHG5M_PCT        = _f("MAX_CHG5M_PCT", 80.0)    # évite pump déjà fini
MIN_CHG1H_PCT        = _f("MIN_CHG1H_PCT", 8.0)     # tendance
MAX_CHG1H_PCT        = _f("MAX_CHG1H_PCT", 250.0)

# --- Anti-noise / structure ---
MIN_TRADES5M         = _i("MIN_TRADES5M", 25)       # si tu as ce champ, sinon ignore
MAX_SPREAD_PCT       = _f("MAX_SPREAD_PCT", 2.0)    # si dispo dans overview

# --- Rug risk gates (soft) ---
MAX_TOPHOLDER_PCT    = _f("MAX_TOPHOLDER_PCT", 25.0)  # top1 holder %
MAX_TOP10_PCT        = _f("MAX_TOP10_PCT", 65.0)      # top10 %
REQUIRE_RENOUNCED    = _i("REQUIRE_RENOUNCED", 0)     # si tu checks mint/freeze authority

# --- Scoring weights ---
W_LIQ  = _f("W_LIQ", 1.0)
W_VOL  = _f("W_VOL", 1.2)
W_MOM  = _f("W_MOM", 1.4)
W_RISK = _f("W_RISK", 1.8)

# Decision threshold
SCORE_MIN            = _f("SCORE_MIN", 6.8)

# Cooldowns / trade frequency
BUY_COOLDOWN_SECONDS           = _f("BUY_COOLDOWN_SECONDS", 900)   # 15 min global
BUY_COOLDOWN_PER_MINT_SECONDS  = _f("BUY_COOLDOWN_PER_MINT_SECONDS", 3600) # 1h per mint
MAX_TRADES_PER_HOUR            = _i("MAX_TRADES_PER_HOUR", 3)
