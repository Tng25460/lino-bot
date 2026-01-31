from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import aiohttp


logger = logging.getLogger("TokenScanner")

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) LinoBot/1.0",
}

DEX_BASE = "https://api.dexscreener.com"


def _cfg_get(cfg: Any, *names: str, default: Any = None) -> Any:
    """Retourne cfg.<name> pour le 1er name existant, sinon default."""
    for n in names:
        if hasattr(cfg, n):
            return getattr(cfg, n)
    return default


class _RateLimiter:
    """Simple rate limiter: max rps (requests/sec)."""

    def __init__(self, rps: float):
        self.rps = max(0.1, float(rps))
        self._lock = asyncio.Lock()
        self._next_ts = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next_ts:
                await asyncio.sleep(self._next_ts - now)
            self._next_ts = max(self._next_ts, time.monotonic()) + (1.0 / self.rps)


@dataclass
class ScannerConfig:
    # compat main.py / anciens patchs
    new_listing_limit: int = 30
    global_rps: float = 2.0
    max_concurrency: int = 1

    # DexScreener search config
    chain: str = "solana"
    dexes: Optional[List[str]] = None
    queries: Optional[List[str]] = None

    # filters
    min_liquidity_usd: float = 2500.0
    min_tx_per_min: float = 2.0
    max_market_cap_usd: Optional[float] = None

    # scoring weights (simple)
    w_tpm: float = 1.0
    w_vol_m5: float = 0.002
    w_liq: float = 0.00002

    def __post_init__(self) -> None:
        if self.dexes is None:
            self.dexes = ["raydium", "pumpfun"]
        if self.queries is None:
            self.queries = ["pump", "raydium", "bonk", "wif", "sol"]


class TokenScanner:
    """
    DexScreener scanner.
    Retourne une liste d'overviews "compat trading.py":
      - ov['data'] = raw DexScreener pair dict (IMPORTANT)
      - ov['_raw'] = raw pair aussi (debug)
      - champs plats: mint, sym/symbol, liquidity/volume/txns, tpm, score, etc.
    """

    def __init__(self, cfg: Any):
        # accepte soit ScannerConfig soit module settings
        if isinstance(cfg, ScannerConfig):
            self.cfg = cfg
        else:
            self.cfg = ScannerConfig(
                new_listing_limit=int(_cfg_get(cfg, "new_listing_limit", "scan_limit", default=30)),
                global_rps=float(_cfg_get(cfg, "global_rps", "scanner_rps", "RPS", default=2.0)),
                max_concurrency=int(_cfg_get(cfg, "max_concurrency", "scanner_concurrency", default=1)),
                chain=str(_cfg_get(cfg, "SCANNER_CHAIN", "chain", default="solana")),
                dexes=list(_cfg_get(cfg, "SCANNER_DEXES", "dexes", default=["raydium", "pumpfun"]) or []),
                queries=list(_cfg_get(cfg, "SCANNER_QUERIES", "queries", default=["pump", "raydium", "bonk", "wif", "sol"]) or []),
                min_liquidity_usd=float(_cfg_get(cfg, "MIN_LIQUIDITY_USD", "min_liquidity_usd", default=2500.0)),
                min_tx_per_min=float(_cfg_get(cfg, "MIN_TX_PER_MIN", "min_tx_per_min", default=2.0)),
                max_market_cap_usd=_cfg_get(cfg, "MAX_MARKET_CAP_USD", "max_market_cap_usd", default=None),
            )

        self._rl = _RateLimiter(self.cfg.global_rps)
        self._sem = asyncio.Semaphore(max(1, int(self.cfg.max_concurrency)))

        logger.info("[Scanner] ✅ limit=%s rps=%s conc=%s", self.cfg.new_listing_limit, self.cfg.global_rps, self.cfg.max_concurrency)

    # ---- public API expected by main.py ----
    async def scan_once_async(self) -> List[Dict[str, Any]]:
        pairs = await self._fetch_pairs()

        overviews: List[Dict[str, Any]] = []
        for p in pairs:
            ov = self._to_overview(p)
            if ov is None:
                continue
            overviews.append(ov)

        # tri score desc + cut limit
        overviews.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

        # --- NORMALIZE_KEYS_FOR_TRADINGENGINE ---
        # TradingEngine._maybe_buy attend: dex_id, price_usd, price, liquidity_usd, marketcap_usd
        try:
            for ov in (overviews or []):
                raw = ov.get("data") or ov.get("_raw") or {}

                # dex_id
                if not ov.get("dex_id"):
                    ov["dex_id"] = str(ov.get("dexId") or raw.get("dexId") or "").lower().strip()

                # price_usd / price
                if ov.get("price_usd") in (None, 0, 0.0, ""):
                    px = ov.get("priceUsd") or raw.get("priceUsd") or raw.get("price_usd") or ov.get("price")
                    try:
                        ov["price_usd"] = float(px or 0.0)
                    except Exception:
                        ov["price_usd"] = 0.0

                if ov.get("price") in (None, 0, 0.0, ""):
                    try:
                        ov["price"] = float(ov.get("price_usd") or 0.0)
                    except Exception:
                        ov["price"] = 0.0

                # liquidity_usd
                if ov.get("liquidity_usd") in (None, 0, 0.0, ""):
                    liq = ov.get("liq") or (raw.get("liquidity") or {}).get("usd") or (ov.get("liquidity") or {}).get("usd")
                    try:
                        ov["liquidity_usd"] = float(liq or 0.0)
                    except Exception:
                        ov["liquidity_usd"] = 0.0

                # marketcap_usd
                if ov.get("marketcap_usd") in (None, 0, 0.0, ""):
                    mc = ov.get("marketCap") or raw.get("marketCap") or raw.get("fdv") or ov.get("fdv")
                    try:
                        ov["marketcap_usd"] = float(mc or 0.0)
                    except Exception:
                        ov["marketcap_usd"] = 0.0
        except Exception:
            pass

        return overviews[: int(self.cfg.new_listing_limit)]

    # alias compat (au cas où)
    async def scan(self) -> List[Dict[str, Any]]:
        return await self.scan_once_async()

    async def get_overviews(self) -> List[Dict[str, Any]]:
        return await self.scan_once_async()

    async def fetch_overviews(self) -> List[Dict[str, Any]]:
        return await self.scan_once_async()

    async def scan_overviews(self) -> List[Dict[str, Any]]:
        return await self.scan_once_async()

    # ---- internals ----
    async def _dex_search(self, session: aiohttp.ClientSession, query: str) -> List[Dict[str, Any]]:
        url = f"{DEX_BASE}/latest/dex/search?q={query}"
        await self._rl.wait()
        async with self._sem:
            try:
                async with session.get(url, headers=DEFAULT_HEADERS, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        txt = await resp.text()
                        logger.warning("[DEX] status=%s url=%s body=%s", resp.status, url, txt[:200])
                        return []
                    data = await resp.json()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("[DEX] request error: %s", e)
                return []

        pairs = data.get("pairs") or []
        if not isinstance(pairs, list):
            return []
        return pairs

    async def _fetch_pairs(self) -> List[Dict[str, Any]]:
        qs: Sequence[str] = self.cfg.queries or []
        dexes = set([d.lower() for d in (self.cfg.dexes or [])])

        out: List[Dict[str, Any]] = []
        seen = set()

        async with aiohttp.ClientSession() as session:
            for q in qs:
                pairs = await self._dex_search(session, str(q))
                for p in pairs:
                    if not isinstance(p, dict):
                        continue
                    if (p.get("chainId") or "").lower() != self.cfg.chain.lower():
                        continue
                    dex = (p.get("dexId") or "").lower()
                    if dexes and dex not in dexes:
                        continue

                    pair_addr = p.get("pairAddress") or p.get("pair_address")
                    if not pair_addr:
                        continue
                    key = (p.get("chainId"), dex, pair_addr)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(p)

        return out

    def _to_overview(self, pair: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # raw values
        base = pair.get("baseToken") or {}
        mint = base.get("address") or base.get("mint") or pair.get("baseTokenAddress")
        sym = base.get("symbol") or base.get("ticker")

        liq_usd = float(((pair.get("liquidity") or {}).get("usd") or 0.0))
        vol_m5 = float(((pair.get("volume") or {}).get("m5") or 0.0))
        tx_m5 = (pair.get("txns") or {}).get("m5") or {}
        buys = int(tx_m5.get("buys") or 0)
        sells = int(tx_m5.get("sells") or 0)
        txns_m5 = buys + sells
        tpm = txns_m5 / 5.0 if txns_m5 > 0 else 0.0

        mcap = pair.get("marketCap")
        if mcap is None:
            mcap = pair.get("fdv")
        market_cap = float(mcap) if mcap is not None else 0.0

        # filters
        if liq_usd < float(self.cfg.min_liquidity_usd):
            return None
        if tpm < float(self.cfg.min_tx_per_min):
            return None
        if self.cfg.max_market_cap_usd is not None:
            try:
                if market_cap > float(self.cfg.max_market_cap_usd):
                    return None
            except Exception:
                pass

        # score (simple)
        score = (
            float(self.cfg.w_tpm) * tpm
            + float(self.cfg.w_vol_m5) * vol_m5
            + float(self.cfg.w_liq) * liq_usd
        )

        ov: Dict[str, Any] = {
            # flat fields used in logs / engine
            "mint": mint,
            "sym": sym,
            "symbol": sym,
            "ticker": sym,

            "chainId": pair.get("chainId"),
            "dexId": pair.get("dexId"),
            "pairAddress": pair.get("pairAddress"),
            "url": pair.get("url"),

            "liq": liq_usd,
            "liquidity_usd": liq_usd,
            "liquidity": {"usd": liq_usd},

            "vol_m5": vol_m5,
            "volume_m5_usd": vol_m5,
            "volume": {"m5": vol_m5},

            "txns_m5": txns_m5,
            "tpm": tpm,
            "tx_per_min": tpm,
            "tx_per_minute": tpm,
            "txns": {"m5": {"buys": buys, "sells": sells}},

            "marketCap": market_cap,
            "fdv": float(pair.get("fdv") or market_cap),

            "priceUsd": pair.get("priceUsd"),
            "priceNative": pair.get("priceNative"),

            "score": float(score),

            # keep raw
            "_raw": pair,
        }

        # ✅ IMPORTANT: trading.py lit ov['data'] (DexScreener raw)
        ov["data"] = pair
        return ov
