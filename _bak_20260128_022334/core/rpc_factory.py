from __future__ import annotations

import os
from typing import List, Tuple, Any

from core.solana_rpc_async import SolanaRPCAsync
from core.rpc_pool import SolanaRPCPool


def _parse_urls() -> List[str]:
    # Priority: RPC_URLS (comma-separated) > RPC_URL/RPC_HTTP > default mainnet
    urls_env = (os.getenv("RPC_URLS") or "").strip()
    if urls_env:
        urls = [u.strip() for u in urls_env.split(",") if u.strip()]
        if urls:
            return urls

    one = (os.getenv("RPC_URL") or os.getenv("RPC_HTTP") or "").strip()
    if one:
        return [one]

    return ["https://api.mainnet-beta.solana.com"]


def build_rpc() -> Tuple[Any, str]:
    """
    Returns: (rpc_client, kind)
      kind in {'pool','single'}
    """
    urls = _parse_urls()

    # Tunables (safe defaults)
    timeout_s = float(os.getenv("RPC_TIMEOUT_S", "20"))
    rps = float(os.getenv("RPC_RPS", "2.2"))
    conc = int(os.getenv("RPC_CONC", "2"))
    retries = int(os.getenv("RPC_RETRIES", "6"))
    backoff_base = float(os.getenv("RPC_BACKOFF_BASE_S", "0.35"))
    backoff_cap = float(os.getenv("RPC_BACKOFF_CAP_S", "6.0"))

    if len(urls) >= 2:
        return (
            SolanaRPCPool(
                urls,
                timeout_s=timeout_s,
                rps=rps,
                max_concurrency=conc,
                max_retries=retries,
                backoff_base_s=backoff_base,
                backoff_cap_s=backoff_cap,
            ),
            "pool",
        )

    return (
        SolanaRPCAsync(
            urls[0],
            timeout_s=timeout_s,
            rps=rps,
            max_concurrency=conc,
            max_retries=retries,
            backoff_base_s=backoff_base,
            backoff_cap_s=backoff_cap,
        ),
        "single",
    )
