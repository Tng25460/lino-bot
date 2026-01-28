import logging
from typing import Any, Dict, Optional

log = logging.getLogger("DecisionTrace")

def trace(mint: str, sym: str, action: str, reason: str, extra: Optional[Dict[str, Any]] = None):
    payload = {"mint": mint, "sym": sym, "action": action, "reason": reason}
    if extra:
        payload.update(extra)
    log.info("[DECISION] %s", payload)
