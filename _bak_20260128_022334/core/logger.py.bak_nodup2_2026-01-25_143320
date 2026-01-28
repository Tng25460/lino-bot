# /home/tng25/lino/core/logger.py
import logging
import os
from logging.handlers import RotatingFileHandler

_LOGGER = None

def get_logger(name: str = "lino") -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    level = os.getenv("LOG_LEVEL", "INFO").upper().strip()
    logger = logging.getLogger(name)
    # Avoid duplicate handlers (prevents double log lines)
    if logger.handlers:
        return logger


    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler (optionnel)
    log_path = os.getenv("LOG_FILE", "/home/tng25/lino/lino.log")
    try:
        fh = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        # si le fichier n'est pas accessible, on continue en console
        pass

    _LOGGER = logger
    return logger

# compat
def setup_logger(*args, **kwargs):
    return get_logger()

# compat (certains de tes anciens imports faisaient "from core.logger import logger")
logger = get_logger()
