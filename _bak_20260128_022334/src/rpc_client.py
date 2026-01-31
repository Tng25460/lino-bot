import asyncio
import json
from typing import Any, Dict, Optional, List

import aiohttp


class RpcError(RuntimeError):
    pass


class SolanaRPC:
    def __init__(self, rpc_http: str, timeout_s: int = 25):
        self.rpc_http = (rpc_http or "").strip()
        self.timeout_s = timeout_s

    async def call(self, session: aiohttp.ClientSession, method: str, params: list) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        async with session.post(self.rpc_http, json=payload, timeout=self.timeout_s) as r:
            txt = await r.text()
            try:
                j = json.loads(txt)
            except Exception:
                raise RpcError(f"RPC non-JSON response: {txt[:200]}")

            if "error" in j and j["error"]:
                raise RpcError(json.dumps(j["error"]))
            return j.get("result")

    async def get_latest_blockhash(self, session: aiohttp.ClientSession, commitment: str = "processed") -> str:
        res = await self.call(session, "getLatestBlockhash", [{"commitment": commitment}])
        return res["value"]["blockhash"]

    async def get_balance_lamports(self, session: aiohttp.ClientSession, pubkey: str, commitment: str = "processed") -> int:
        res = await self.call(session, "getBalance", [pubkey, {"commitment": commitment}])
        return int(res["value"])

    async def get_account_info(self, session: aiohttp.ClientSession, pubkey: str, encoding: str = "jsonParsed") -> Dict[str, Any]:
        # encoding=jsonParsed permet de lire facilement les mints SPL (Tokenkeg)
        res = await self.call(session, "getAccountInfo", [pubkey, {"encoding": encoding}])
        return res

    async def get_token_largest_accounts(self, session: aiohttp.ClientSession, mint: str) -> Dict[str, Any]:
        res = await self.call(session, "getTokenLargestAccounts", [mint])
        return res

    async def simulate_transaction(
        self,
        session: aiohttp.ClientSession,
        tx_b64: str,
        commitment: str = "processed",
        replace_recent_blockhash: bool = True,
        sig_verify: bool = False,
    ) -> Dict[str, Any]:
        opts = {
            "encoding": "base64",
            "commitment": commitment,
            "replaceRecentBlockhash": replace_recent_blockhash,
            "sigVerify": sig_verify,
        }
        res = await self.call(session, "simulateTransaction", [tx_b64, opts])
        return res

    async def send_transaction(
        self,
        session: aiohttp.ClientSession,
        tx_b64: str,
        skip_preflight: bool = False,
        preflight_commitment: str = "processed",
        max_retries: int = 3,
    ) -> str:
        opts = {
            "encoding": "base64",
            "skipPreflight": bool(skip_preflight),
            "preflightCommitment": preflight_commitment,
            "maxRetries": int(max_retries),
        }
        res = await self.call(session, "sendTransaction", [tx_b64, opts])
        return str(res)

    async def get_signature_statuses(self, session: aiohttp.ClientSession, sigs: List[str]) -> Dict[str, Any]:
        res = await self.call(session, "getSignatureStatuses", [sigs, {"searchTransactionHistory": True}])
        return res
