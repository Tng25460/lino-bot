import asyncio
from typing import Optional

from core.jupiter_price_async import JupiterPriceV3Async


class JupPriceFeed:
    """
    Price feed sync (get_price) basé sur JupiterPriceV3Async.
    Retourne un prix float (USD) ou None.
    """
    def __init__(self):
        self._jp = JupiterPriceV3Async()

    def get_price(self, mint: str) -> Optional[float]:

        """Return SOL per 1 token using Jupiter /swap/v1/quote with a stable quote size.


        Env:

          PRICE_QUOTE_TOKENS (default 10000): minimum token amount to quote (in tokens, not base units)

          SOLANA_RPC_HTTP (fallback https://api.mainnet-beta.solana.com)

          JUP_BASE_URL (fallback https://lite-api.jup.ag)

        """

        try:

            import os, json, urllib.request

            SOL = "So11111111111111111111111111111111111111112"

            rpc_url = os.getenv("SOLANA_RPC_HTTP") or os.getenv("RPC_HTTP") or "https://api.mainnet-beta.solana.com"

            jup_base = (os.getenv("JUP_BASE_URL") or "https://lite-api.jup.ag").rstrip("/")

            qurl = jup_base + "/swap/v1/quote"

            tokens_q = float(os.getenv("PRICE_QUOTE_TOKENS", "10000") or "10000")

            if tokens_q < 1:

                tokens_q = 1.0


            # decimals via getTokenSupply

            body = json.dumps({"jsonrpc":"2.0","id":1,"method":"getTokenSupply","params":[mint,{"commitment":"processed"}]}).encode()

            req = urllib.request.Request(rpc_url, data=body, headers={"Content-Type":"application/json"})

            resp = json.loads(urllib.request.urlopen(req, timeout=20).read())

            dec = int(resp["result"]["value"]["decimals"])

            amt = int(tokens_q * (10**dec))  # base units


            url = f"{qurl}?inputMint={mint}&outputMint={SOL}&amount={amt}&slippageBps=50"

            q = json.loads(urllib.request.urlopen(url, timeout=20).read())

            out_lamports = int(q.get("outAmount") or 0)

            if out_lamports <= 0:

                return None

            sol_out = out_lamports / 1e9

            sol_per_token = sol_out / tokens_q

            return float(sol_per_token)

        except Exception:

            return None

