import json
import time
from pathlib import Path
from typing import Any, Dict, List

POSITIONS_PATH = Path("state/positions_live.json")

def load_positions() -> List[Dict[str, Any]]:
    if not POSITIONS_PATH.exists():
        return []
    try:
        return json.loads(POSITIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_positions(pos: List[Dict[str, Any]]) -> None:
    POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSITIONS_PATH.write_text(json.dumps(pos, indent=2), encoding="utf-8")

def upsert_position(p: Dict[str, Any]) -> None:
    pos = load_positions()
    mint = str(p.get("mint") or "").strip()
    pos = [x for x in pos if str(x.get("mint") or "").strip() != mint]
    pos.append(p)
    save_positions(pos)

def mark_closed(mint: str, close_sig: str, reason: str) -> None:
    pos = load_positions()
    now = int(time.time())
    for x in pos:
        if str(x.get("mint") or "").strip() == mint and not x.get("closed_ts"):
            x["closed_ts"] = now
            x["close_sig"] = close_sig
            x["close_reason"] = reason
    save_positions(pos)
