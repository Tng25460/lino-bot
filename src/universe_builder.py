import os
import json
from pathlib import Path
from typing import Any, Dict, List
import requests

JUP_BASE = os.getenv("JUP_BASE", "https://api.jup.ag").rstrip("/")
TOKENS_BASE = os.getenv("JUP_TOKENS_BASE", f"{JUP_BASE}/tokens/v2").rstrip("/")
JUP_API_KEY = os.getenv("JUP_API_KEY", "").strip()

TOP_N = int(os.getenv("UNIVERSE_TOP_N", "1200"))
MAX_OUT = int(os.getenv("UNIVERSE_MAX_OUT", "250"))

MIN_VOL_24H = float(os.getenv("UNIVERSE_MIN_VOL_24H", "50000"))
MIN_VOL_1H = float(os.getenv("UNIVERSE_MIN_VOL_1H", "5000"))
MIN_LIQ = float(os.getenv("UNIVERSE_MIN_LIQ", "40000"))
MIN_TRADERS_1H = int(os.getenv("UNIVERSE_MIN_TRADERS_1H", "20"))
MIN_HOLDERS = int(os.getenv("UNIVERSE_MIN_HOLDERS", "800"))
MIN_ORGANIC = float(os.getenv("UNIVERSE_MIN_ORGANIC", "35"))

REQUIRE_VERIFIED = os.getenv("UNIVERSE_REQUIRE_VERIFIED", "0").strip().lower() in ("1","true","yes","on")
REQUIRE_AUTH_DISABLED = os.getenv("UNIVERSE_REQUIRE_AUTH_DISABLED", "0").strip().lower() in ("1","true","yes","on")
MAX_TOP_HOLD_PCT = float(os.getenv("UNIVERSE_MAX_TOP_HOLD_PCT", "60"))
REJECT_DEBUG = os.getenv("UNIVERSE_REJECT_DEBUG", "0").strip().lower() in ("1","true","yes","on")

STATE_DIR = Path("state")
STATE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_PATH = STATE_DIR / "universe_cache.json"

def _headers() -> Dict[str, str]:
    h = {"accept": "application/json"}
    if JUP_API_KEY:
        h["x-api-key"] = JUP_API_KEY
    return h

def _get_json(url: str, timeout: int = 20) -> Any:
    r = requests.get(url, headers=_headers(), timeout=timeout)
    r.raise_for_status()
    return r.json()

def _f(x: Any, d: float = 0.0) -> float:
    try:
        return d if x is None else float(x)
    except Exception:
        return d

def _i(x: Any, d: int = 0) -> int:
    try:
        return d if x is None else int(x)
    except Exception:
        return d

def fetch_feed(feed: str, interval: str, limit: int = 100) -> List[Dict[str, Any]]:
    url = f"{TOKENS_BASE}/{feed}/{interval}?limit={limit}"
    data = _get_json(url)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("data","result","items","tokens"):
            v = data.get(k)
            if isinstance(v, list):
                return v
    return []

def build_universe() -> List[Dict[str, Any]]:
    print("🧠 universe_builder")
    print("   jup_base=", JUP_BASE)
    print("   tokens_base=", TOKENS_BASE)
    print(f"   top_n= {TOP_N} max_out= {MAX_OUT}")
    print(f"   filters: daily_vol>= {MIN_VOL_24H} liq>= {MIN_LIQ} vol1h>= {MIN_VOL_1H} "
          f"traders1h>= {MIN_TRADERS_1H} holders>= {MIN_HOLDERS} organic>= {MIN_ORGANIC} "
          f"verified= {REQUIRE_VERIFIED} auth_disabled= {REQUIRE_AUTH_DISABLED} topHold%<= {MAX_TOP_HOLD_PCT}")

    feeds = [
        ("toptraded", "24h", 100),
        ("toptrending", "1h", 100),
        ("toporganicscore", "24h", 100),
    ]

    candidates: List[Dict[str, Any]] = []
    for name, interval, lim in feeds:
        try:
            candidates.extend(fetch_feed(name, interval, lim))
        except Exception as e:
            print(f"❌ feed fail {name}/{interval}: {e}")

    by_id: Dict[str, Dict[str, Any]] = {}
    for t in candidates:
        mid = t.get("id") or t.get("mint") or t.get("address")
        if mid:
            by_id[str(mid)] = t
    merged = list(by_id.values())
    print("   candidates_merged=", len(merged))

    out: List[Dict[str, Any]] = []
    for t in merged:
        mid = t.get("id") or t.get("mint") or t.get("address")
        if not mid:
            continue
        mid = str(mid)

        liquidity = _f(t.get("liquidity"), 0.0)
        holders = _i(t.get("holderCount"), 0)
        organic = _f(t.get("organicScore"), 0.0)

        audit = t.get("audit") or {}
        top_hold_pct = _f(audit.get("topHoldersPercentage"), 0.0)
        mint_auth_disabled = bool(audit.get("mintAuthorityDisabled"))
        freeze_auth_disabled = bool(audit.get("freezeAuthorityDisabled"))
        is_verified = bool(t.get("isVerified"))

        s1h = t.get("stats1h") or {}
        s24 = t.get("stats24h") or {}
        vol_1h = _f(s1h.get("buyVolume"), 0.0) + _f(s1h.get("sellVolume"), 0.0)
        vol_24h = _f(s24.get("buyVolume"), 0.0) + _f(s24.get("sellVolume"), 0.0)
        traders_1h = _i(s1h.get("numTraders"), 0)

        if vol_24h < MIN_VOL_24H: continue
        if vol_1h < MIN_VOL_1H: continue
        if liquidity < MIN_LIQ: continue
        if traders_1h < MIN_TRADERS_1H: continue
        if holders < MIN_HOLDERS: continue
        if organic < MIN_ORGANIC: continue
        if top_hold_pct > MAX_TOP_HOLD_PCT:
            if REJECT_DEBUG:
                print(f"   reject {t.get('symbol','?')} topHold%={top_hold_pct:.2f} > {MAX_TOP_HOLD_PCT}")
            continue
        if REQUIRE_VERIFIED and not is_verified: continue
        if REQUIRE_AUTH_DISABLED and not (mint_auth_disabled and freeze_auth_disabled): continue

        out.append({
            "mint": mid,
            "symbol": t.get("symbol"),
            "name": t.get("name"),
            "liquidity": liquidity,
            "holderCount": holders,
            "organicScore": organic,
            "topHoldersPercentage": top_hold_pct,
            "vol1h": vol_1h,
            "vol24h": vol_24h,
            "traders1h": traders_1h,
            "usdPrice": t.get("usdPrice"),
        })
        if len(out) >= MAX_OUT:
            break

    CACHE_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ cached universe -> {CACHE_PATH} size= {len(out)}")
    return out

if __name__ == "__main__":
    build_universe()
