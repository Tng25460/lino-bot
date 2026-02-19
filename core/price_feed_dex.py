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

    def get_price(self, mint: str) -> Optional[float]:

        # Delegate to Jupiter-style quote logic for stable SOL/token pricing

        try:

            import os, json, urllib.request

            SOL = "So11111111111111111111111111111111111111112"

            rpc_url = os.getenv("SOLANA_RPC_HTTP") or os.getenv("RPC_HTTP") or "https://api.mainnet-beta.solana.com"

            jup_base = (os.getenv("JUP_BASE_URL") or "https://lite-api.jup.ag").rstrip("/")

            qurl = jup_base + "/swap/v1/quote"

            tokens_q = float(os.getenv("PRICE_QUOTE_TOKENS", "10000") or "10000")

            if tokens_q < 1:

                tokens_q = 1.0


            body = json.dumps({"jsonrpc":"2.0","id":1,"method":"getTokenSupply","params":[mint,{"commitment":"processed"}]}).encode()

            req = urllib.request.Request(rpc_url, data=body, headers={"Content-Type":"application/json"})

            resp = _urlopen_json_429(req, timeout=20, retries=int(os.getenv('PRICE_RPC_RETRIES','3')), base_sleep=float(os.getenv('PRICE_RPC_SLEEP','0.35')), tag='rpc')

            dec = int(resp["result"]["value"]["decimals"])

            amt = int(tokens_q * (10**dec))


            url = f"{qurl}?inputMint={mint}&outputMint={SOL}&amount={amt}&slippageBps=50"


            try:
                q = _urlopen_json_429(url, timeout=20, retries=int(os.getenv('PRICE_QUOTE_RETRIES','3')), base_sleep=float(os.getenv('PRICE_QUOTE_SLEEP','0.35')), tag='quote')
            except Exception as e:
                print(f"[WARN] price_feed_dex get_price failed mint={mint} err={type(e).__name__}:{e}")
                return None


            out_lamports = int(q.get("outAmount") or 0)

            if out_lamports <= 0:

                return None

            sol_out = out_lamports / 1e9

            return float(sol_out / tokens_q)

        except Exception:

            return None

