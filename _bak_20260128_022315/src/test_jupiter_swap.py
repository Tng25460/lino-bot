# src/test_jupiter_swap.py

import asyncio

from core.wallet import Wallet
from core.raydium_client import RaydiumClient
from config.settings import RPC_URL


USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


async def main():
    print("=== Test swap Jupiter (SOL -> USDC) ===")

    # 1) Charger le wallet
    wallet = Wallet()
    print(f"[WALLET] Public key: {wallet.pubkey()}")

    # 2) Vérifier le solde SOL
    sol_balance = await wallet.get_sol_balance()
    print(f"[WALLET] Solde actuel: {sol_balance:.6f} SOL")

    # Si le solde est trop bas, on n'essaie même pas de swap
    min_needed = 0.02  # 0.01 pour le swap + marge pour les frais
    if sol_balance < min_needed:
        print(
            f"[TEST] Solde insuffisant ({sol_balance:.6f} SOL). "
            f"Il faut au moins ~{min_needed} SOL pour ce test."
        )
        print("=== Fin du test Jupiter (solde insuffisant) ===")
        return

    # 3) Init client Jupiter/Raydium
    client = RaydiumClient(rpc_url=RPC_URL)

    try:
        amount_sol = 0.01
        print(f"[TEST] Tentative de swap {amount_sol} SOL -> USDC")

        ok = await client.swap_sol_to_token(
            keypair=wallet.keypair(),
            token_mint=USDC_MINT,
            amount_sol=amount_sol,
            slippage_bps=100,  # 1% de slippage
        )

        if ok:
            print("[RESULT] Swap SOL -> USDC RÉUSSI.")
        else:
            print("[RESULT] Swap SOL -> USDC ÉCHOUÉ (voir logs ci-dessus).")

    finally:
        await client.close()
        print("=== Fin du test Jupiter ===")


if __name__ == "__main__":
    asyncio.run(main())
