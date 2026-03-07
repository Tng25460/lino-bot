import time
import random
def _urlopen_json_429(req_or_url, timeout=20, retries=3, base_sleep=0.35, tag=""):
    """
    urlopen -> json.loads with retry on HTTP 429 only.
    retries=3 => up to 3 attempts (0,1,2).
    """
    import json, time, urllib.request, urllib.error
    last = None
    for attempt in range(int(retries)):
        try:
            data = urllib.request.urlopen(req_or_url, timeout=timeout).read()
            return json.loads(data)
        except urllib.error.HTTPError as e:
            last = e
            code = getattr(e, "code", None)
            if code == 429 and attempt < int(retries) - 1:
                time.sleep(base_sleep * (2 ** attempt))
                continue
            raise
        except Exception as e:
            last = e
            # no retry except 429
            raise
    raise last

import requests
from typing import Optional
import os
DEX_TIMEOUT = float(os.getenv("DEX_TIMEOUT", "4"))

class DexScreenerPriceFeed:
    """
    Price feed sync sans API key.
    Utilise DexScreener: https://api.dexscreener.com/latest/dex/tokens/<mint>
    Retourne priceUsd float ou None.
    """
    def __init__(self):
        self.s = requests.Session()

    def _get_price_raw(self, mint: str) -> Optional[float]:

        # Delegate to Jupiter-style quote logic for stable SOL/token pricing

        try:

            import os, json, urllib.request

            SOL = "So11111111111111111111111111111111111111112"

            rpc_url = os.getenv("SOLANA_RPC_HTTP") or os.getenv("RPC_HTTP") or "https://api.mainnet-beta.solana.com"

            jup_base = (os.getenv("JUP_BASE_URL") or "https://lite-api.jup.ag").rstrip("/")

            qurl = jup_base + "/swap/v1/quote"

            # PRICE_QUOTE_MULTI_V1:
            # On essaye plusieurs tailles de quote pour éviter les 400 sur tokens illiquides.
            # Env:
            #   PRICE_QUOTE_TOKENS (default 10000)
            #   PRICE_QUOTE_SLIPPAGE_BPS (default 300)
            base_tokens_q = float(os.getenv("PRICE_QUOTE_TOKENS", "10000") or "10000")
            if base_tokens_q < 1:
                base_tokens_q = 1.0

            slip_bps = int(float(os.getenv("PRICE_QUOTE_SLIPPAGE_BPS", "300") or "300"))
            if slip_bps < 20:
                slip_bps = 20

            # liste décroissante, puis fallback à 1 token
            q_list = []
            for div in (1, 10, 100, 1000):
                v = base_tokens_q / div
                if v >= 1:
                    q_list.append(v)
            if 1.0 not in q_list:
                q_list.append(1.0)


            body = json.dumps({"jsonrpc":"2.0","id":1,"method":"getTokenSupply","params":[mint,{"commitment":"processed"}]}).encode()

            req = urllib.request.Request(rpc_url, data=body, headers={"Content-Type":"application/json"})

            resp = _urlopen_json_429(req, timeout=20, retries=int(os.getenv('PRICE_RPC_RETRIES','3')), base_sleep=float(os.getenv('PRICE_RPC_SLEEP','0.35')), tag='rpc')

            dec = int(resp["result"]["value"]["decimals"])

            # Essaie plusieurs tailles de quote (q_list) pour éviter les 400.
            last_err = None
            for tokens_q in q_list:
                try:
                    amt = int(tokens_q * (10**dec))
                    url = f"{qurl}?inputMint={mint}&outputMint={SOL}&amount={amt}&slippageBps={slip_bps}"
                    q = _urlopen_json_429(
                        url,
                        timeout=20,
                        retries=int(os.getenv('PRICE_QUOTE_RETRIES','3')),
                        base_sleep=float(os.getenv('PRICE_QUOTE_SLEEP','0.35')),
                        tag='quote'
                    )
                    out_lamports = int(q.get("outAmount") or 0)
                    if out_lamports > 0:
                        sol_out = out_lamports / 1e9
                        return float(sol_out / tokens_q)
                    # outAmount==0 => on tente plus petit
                except Exception as e:
                    last_err = e
                    code = getattr(e, "code", None)
                    # 400/404/422: souvent "no route / bad params" pour un montant trop gros => tente plus petit
                    if code in (400, 404, 422):
                        continue
                    print(f"[WARN] price_feed_dex get_price failed mint={mint} err={type(e).__name__}:{e}")
                    return None

            # si tout échoue, log en DBG et None
            if last_err is not None:
                code = getattr(last_err, "code", None)
                if code in (400, 404, 422):
                    print(f"[DBG] price_feed_dex get_price soft-fail mint={mint} code={code} err={type(last_err).__name__}:{last_err}")
            return None



            out_lamports = int(q.get("outAmount") or 0)

            if out_lamports <= 0:

                return None

            sol_out = out_lamports / 1e9

            return float(sol_out / tokens_q)

        except Exception:

            return None



    # DEX_THROTTLE_WRAP_V1: throttle+cache wrapper around DexScreener calls
    # Env:
    #   DEX_THROTTLE_SLEEP_SEC (default 0.6)
    #   DEX_CACHE_TTL_SEC      (default 12)
    #   DEX_429_BACKOFF_SEC    (default 3.0)
    #   DEX_429_JITTER_SEC     (default 0.7)

    _dex_last_call = 0.0
    _dex_cache = {}

    def get_price(self, mint: str):
        now = time.time()

        # cache
        ttl = float(__import__("os").getenv("DEX_CACHE_TTL_SEC", "12"))
        neg_ttl = float(__import__("os").getenv("DEX_NEG_CACHE_TTL_SEC", "180"))  # DEX_400_SOFT_V1: cache TTL when price is None
        c = self._dex_cache.get(mint)
        if c:
            age = now - float(c[0] or 0.0)
            px0 = c[1] if len(c) > 1 else None
            # DEX_400_SOFT_V1: negative cache for None price
            if px0 is None:
                if age < neg_ttl:
                    return None
            else:
                if age < ttl:
                    return px0

        # throttle global (par instance)
        sleep_s = float(__import__("os").getenv("DEX_THROTTLE_SLEEP_SEC", "0.6"))
        dt = now - float(self._dex_last_call or 0.0)
        if dt < sleep_s:
            time.sleep(sleep_s - dt)

        self._dex_last_call = time.time()

        try:
            px = self._get_price_raw(mint)
        except Exception as e:
            # DEX_400_SOFT_V1: soften bad-request errors (400/404/422) + negative cache
            code = getattr(e, "code", None)
            if code in (400, 404, 422):
                self._dex_cache[mint] = (time.time(), None)
                return None

            # backoff simple sur 429 si présent dans le message
            msg = str(e)
            if code == 429 or "HTTP Error 429" in msg or "429" in msg:
                base = float(__import__("os").getenv("DEX_429_BACKOFF_SEC", "3.0"))
                jit  = float(__import__("os").getenv("DEX_429_JITTER_SEC",  "0.7"))
                time.sleep(base + random.random() * jit)
            raise

        # DEX_400_SOFT_V1: if no price, negative cache and return
        if px is None:
            self._dex_cache[mint] = (time.time(), None)
            return None

        # store cache
        self._dex_cache[mint] = (time.time(), px)
        return px

