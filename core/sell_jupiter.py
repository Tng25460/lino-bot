import os
from solders.keypair import Keypair

from core.solana_rpc_async import SolanaRPCAsync
from core.jupiter_exec import jup_sell_exact_in

WSOL_MINT = os.getenv("WSOL_MINT", "So11111111111111111111111111111111111111112")

SELL_MIN_SOL_BUFFER_SOL = float(os.getenv("SELL_MIN_SOL_BUFFER_SOL", "0.003"))
SELL_MIN_SOL_BUFFER_LAMPORTS = int(SELL_MIN_SOL_BUFFER_SOL * 1_000_000_000)

SELL_SKIP_IF_LOW_SOL = os.getenv("SELL_SKIP_IF_LOW_SOL", "1").strip() not in ("0","false","False")


async def _get_balance_lamports(rpc: SolanaRPCAsync, pubkey_str: str) -> int:
    if hasattr(rpc, "get_balance"):
        v = await rpc.get_balance(pubkey_str)
        return int(v)
    resp = await rpc.call("getBalance", [pubkey_str, {"commitment":"processed"}])
    return int(resp["value"])


async def sell_token_for_sol(
    rpc: SolanaRPCAsync,
    wallet: Keypair,
    token_mint: str,
    amount_raw: int,
) -> str:
    pub = str(wallet.pubkey())
    bal = await _get_balance_lamports(rpc, pub)

    if SELL_SKIP_IF_LOW_SOL and bal < SELL_MIN_SOL_BUFFER_LAMPORTS:
        return f"SKIP_LOW_SOL balance_sol={bal/1e9:.6f} need>={SELL_MIN_SOL_BUFFER_SOL:.6f}"

    return await jup_sell_exact_in(
        rpc=rpc,
        wallet=wallet,
        input_mint=token_mint,
        output_mint=WSOL_MINT,
        amount_in=amount_raw,
    )
