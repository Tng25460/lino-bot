import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

# ---------------------------
# Files: blacklist dev / mint
# ---------------------------


def ultra_get_dev(mint: str) -> str:
    """
    Récupère l'adresse dev/creator depuis Jupiter Ultra search.
    Best-effort: retourne "" si introuvable.
    """
    import os, requests
    JUP = (os.getenv("JUPITER_BASE_URL") or "https://api.jup.ag").rstrip("/")
    KEY = (os.getenv("JUPITER_API_KEY") or "").strip()
    h = {"accept": "application/json"}
    if KEY:
        h["x-api-key"] = KEY

    try:
        r = requests.get(f"{JUP}/ultra/v1/search", params={"query": mint}, headers=h, timeout=20)
        r.raise_for_status()
        arr = r.json() or []
        if not arr:
            return ""
        t = arr[0]
        dev = (t.get("dev") or "").strip()
        return dev
    except Exception:
        return ""

BLACKLIST_DEV_PATH = Path("state/blacklist_dev.json")
BLACKLIST_MINT_PATH = Path("state/blacklist_mint.json")


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8") or "")
    except Exception:
        return default


def _save_json(path: Path, obj: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_blacklist_dev() -> Dict[str, str]:
    return _load_json(BLACKLIST_DEV_PATH, {})


def blacklist_dev(dev: str, reason: str):
    dev = (dev or "").strip()
    if not dev:
        return
    bl = _load_blacklist_dev()
    bl[dev] = reason or "BAD_DEV"
    _save_json(BLACKLIST_DEV_PATH, bl)
    print(f"⛔ DEV BLACKLISTED {dev[:6]}… reason={reason}")


def is_dev_blacklisted(dev: str) -> bool:
    dev = (dev or "").strip()
    if not dev:
        return False
    return dev in _load_blacklist_dev()


def _load_blacklist_mint() -> Dict[str, Dict[str, Any]]:
    # format: { mint: {"reason": "...", "until": epoch} }
    return _load_json(BLACKLIST_MINT_PATH, {})


def blacklist_mint(mint: str, reason: str, ttl_sec: int = 900):
    mint = (mint or "").strip()
    if not mint:
        return
    bl = _load_blacklist_mint()
    bl[mint] = {"reason": reason or "BAD_MINT", "until": int(time.time()) + int(ttl_sec)}
    _save_json(BLACKLIST_MINT_PATH, bl)
    print(f"⛔ TOKEN BLACKLISTED {mint[:6]}… {reason}")


def is_mint_blacklisted(mint: str) -> bool:
    mint = (mint or "").strip()
    if not mint:
        return False
    bl = _load_blacklist_mint()
    now = int(time.time())

    # expire
    changed = False
    for k in list(bl.keys()):
        until = int(bl[k].get("until") or 0)
        if until and until < now:
            del bl[k]
            changed = True
    if changed:
        _save_json(BLACKLIST_MINT_PATH, bl)

    return mint in bl


# ---------------------------
# Jupiter Ultra risk scoring
# ---------------------------
def _jup_headers() -> Dict[str, str]:
    h = {"accept": "application/json"}
    key = (os.getenv("JUPITER_API_KEY") or os.getenv("JUPITER_KEY") or "").strip()
    if key:
        h["x-api-key"] = key
    return h


def _ultra_lookup_by_mint(mint: str) -> Dict[str, Any]:
    """
    On interroge Ultra search avec le mint lui-même (ça marche très bien en pratique).
    On prend l'item dont id == mint si présent, sinon le premier.
    """
    base = (os.getenv("JUPITER_BASE_URL") or "https://api.jup.ag").rstrip("/")
    url = f"{base}/ultra/v1/search"
    r = requests.get(url, params={"query": mint}, headers=_jup_headers(), timeout=25)
    r.raise_for_status()
    arr = r.json() or []
    if not arr:
        return {}
    for it in arr:
        if str(it.get("id") or "") == mint:
            return it
    return arr[0] or {}


def risk_check(mint: str) -> Tuple[bool, int, List[str], Dict[str, Any]]:
    """
    Retour: (ok, score, reasons, details)
    - ok: bool
    - score: 0..100
    - reasons: liste
    - details: dict debug
    """
    mint = (mint or "").strip()
    if not mint or not (32 <= len(mint) <= 60):
        return (False, 0, ["INVALID_MINT"], {})

    if is_mint_blacklisted(mint):
        bl = _load_blacklist_mint().get(mint, {})
        return (False, 0, ["MINT_BLACKLISTED"], {"blacklist": bl})

    # seuils (tu peux ajuster via env)
    MIN_LIQ_USD = float(os.getenv("RISK_MIN_LIQ_USD", "150000"))      # 150k$
    MAX_TOP_HOLD_PCT = float(os.getenv("RISK_MAX_TOP_HOLD_PCT", "35"))# <=35%
    MIN_HOLDERS = int(os.getenv("RISK_MIN_HOLDERS", "5000"))          # 5k holders
    REQUIRE_AUTH_DISABLED = os.getenv("RISK_REQUIRE_AUTH_DISABLED", "1") == "1"  # mint+freeze off

    try:
        it = _ultra_lookup_by_mint(mint)
    except Exception as e:
        # fallback SAFE (ne bloque pas tout)
        return (True, 50, ["ULTRA_ERROR_FALLBACK"], {"err": str(e)})

    if not it:
        # pas de data -> fallback SAFE mais score moyen
        return (True, 45, ["NO_ULTRA_DATA_FALLBACK"], {})

    audit = it.get("audit") or {}
    dev = (it.get("dev") or "").strip()
    liquidity = float(it.get("liquidity") or 0.0)      # Ultra renvoie souvent une "liquidity" (souvent USD)
    holders = int(it.get("holderCount") or 0)
    verified = bool(it.get("isVerified") or False)

    mintAuthDisabled = bool(audit.get("mintAuthorityDisabled") is True)
    freezeAuthDisabled = bool(audit.get("freezeAuthorityDisabled") is True)
    topHoldPct = float(audit.get("topHoldersPercentage") or 100.0)

    details = {
        "name": it.get("name"),
        "symbol": it.get("symbol"),
        "dev": dev,
        "liquidity": liquidity,
        "holderCount": holders,
        "isVerified": verified,
        "audit": audit,
        "topHoldersPercentage": topHoldPct,
        "mintAuthorityDisabled": mintAuthDisabled,
        "freezeAuthorityDisabled": freezeAuthDisabled,
    }

    # DEV blacklist
    if dev and is_dev_blacklisted(dev):
        return (False, 0, ["DEV_BLACKLISTED"], details)

    # Règles hard reject (anti-rug)
    reasons: List[str] = []
    if REQUIRE_AUTH_DISABLED:
        if not mintAuthDisabled:
            reasons.append("MINT_AUTH_NOT_DISABLED")
        if not freezeAuthDisabled:
            reasons.append("FREEZE_AUTH_NOT_DISABLED")

    if topHoldPct > MAX_TOP_HOLD_PCT:
        reasons.append(f"TOP_HOLDERS_TOO_HIGH:{topHoldPct:.2f}%")

    if liquidity > 0 and liquidity < MIN_LIQ_USD:
        reasons.append(f"LOW_LIQ:{liquidity:.0f}")

    if holders > 0 and holders < MIN_HOLDERS:
        reasons.append(f"LOW_HOLDERS:{holders}")

    # score (simple & lisible)
    score = 80
    if verified:
        score += 10
    if liquidity >= MIN_LIQ_USD:
        score += 5
    if topHoldPct <= 25:
        score += 5

    # pénalités
    if reasons:
        score = max(0, 30 - 5 * len(reasons))

    ok = (len(reasons) == 0)
    return (ok, int(score), reasons, details)
