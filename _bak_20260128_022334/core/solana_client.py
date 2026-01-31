import os
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
import json

class SolanaClient:
    def __init__(self):
        self.rpc_url = "https://api.mainnet-beta.solana.com"
        self.rpc = AsyncClient(self.rpc_url)

        # Charger la keypair depuis keypair.json par exemple
        with open("keypair.json", "r") as f:
            secret_key = json.load(f)
        raw = bytes(secret_key)
        if len(raw) == 64:
            self.keypair = Keypair.from_bytes(raw)
        elif len(raw) == 32:
            self.keypair = Keypair.from_seed(raw)
        else:
            raise ValueError(f"secret_key length invalid: {len(raw)} (expected 32 or 64)")
# optionnel : clé API Jupiter
        self.jupiter_api_key = (os.getenv("JUPITER_API_KEY") or "").strip()


    async def get_token_balance(self, mint: str):
        """
        Retourne le solde du token `mint` pour le wallet (UI amount, ex: 12.34).
        Supporte:
          - SPL Token program (Tokenkeg...)
          - Token-2022 program (TokenzQd...)
        Robust:
          - si RPC renvoie raw amount/decimals, on reconstruit
          - si aucune account trouvée => 0.0
        """
        # --------- owner pubkey (on essaye plusieurs attributs possibles) ----------
        owner = None
        for cand in (
            getattr(self, "wallet_pubkey", None),
            getattr(self, "pubkey", None),
            getattr(getattr(self, "wallet", None), "pubkey", None),
            getattr(getattr(self, "wallet", None), "public_key", None),
            getattr(getattr(self, "keypair", None), "pubkey", None),
            getattr(getattr(self, "keypair", None), "public_key", None),
        ):
            if cand:
                owner = cand
                break
        if owner is None:
            raise RuntimeError("SolanaClient: owner pubkey introuvable (wallet_pubkey/pubkey/wallet.keypair...)")

        # --------- RPC client (AsyncClient solana-py le plus souvent) ----------
        client = getattr(self, "client", None) or getattr(self, "rpc", None) or getattr(self, "_client", None)
        if client is None:
            raise RuntimeError("SolanaClient: client RPC introuvable (self.client/self.rpc/self._client)")

        TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

        async def _fetch_for_program(program_id: str):
            # solana-py: get_token_accounts_by_owner(owner, mint=..., program_id=...)
            if hasattr(client, "get_token_accounts_by_owner"):
                try:
                    return await client.get_token_accounts_by_owner(
                        owner,
                        mint=mint,
                        program_id=program_id,
                        encoding="jsonParsed",
                    )
                except TypeError:
                    # certaines versions n'ont pas named args
                    return await client.get_token_accounts_by_owner(owner, {"mint": mint}, program_id, "jsonParsed")
            # fallback JSON RPC brut si jamais
            if hasattr(client, "_provider") and hasattr(client._provider, "make_request"):
                params = [
                    str(owner),
                    {"mint": mint},
                    {"encoding": "jsonParsed", "programId": program_id},
                ]
                return await client._provider.make_request("getTokenAccountsByOwner", *params)
            raise RuntimeError("SolanaClient: impossible d'appeler getTokenAccountsByOwner (API inconnue)")

        def _extract_sum(resp):
            """
            Supporte formes:
              - solana-py: resp.value = list
              - resp['result']['value'] = list
              - resp.result.value
            """
            # normalise "value"
            value = None
            for cand in (
                getattr(resp, "value", None),
                getattr(getattr(resp, "result", None), "value", None),
            ):
                if cand is not None:
                    value = cand
                    break
            if value is None and isinstance(resp, dict):
                value = resp.get("result", {}).get("value", None)

            if not value:
                return 0.0

            total_ui = 0.0
            for acc in value:
                # solana-py: acc.account.data.parsed.info.tokenAmount
                token_amount = None
                try:
                    token_amount = acc["account"]["data"]["parsed"]["info"]["tokenAmount"]
                except Exception:
                    try:
                        token_amount = acc.account.data.parsed["info"]["tokenAmount"]
                    except Exception:
                        try:
                            token_amount = acc["account"]["data"]["parsed"]["info"].get("tokenAmount")
                        except Exception:
                            token_amount = None

                if not token_amount:
                    continue

                # uiAmount direct si dispo
                ui = token_amount.get("uiAmount", None)
                if ui is not None:
                    total_ui += float(ui)
                    continue

                # sinon: amount (string int) + decimals
                amt = token_amount.get("amount", "0")
                dec = int(token_amount.get("decimals", 0))
                try:
                    total_ui += int(amt) / (10 ** dec if dec else 1)
                except Exception:
                    pass

            return float(total_ui)

        # Essayons Tokenkeg puis Token-2022, on additionne
        r1 = await _fetch_for_program(TOKEN_PROGRAM)
        r2 = await _fetch_for_program(TOKEN_2022_PROGRAM)

        return float(_extract_sum(r1) + _extract_sum(r2))

    def get_keypair(self):
        return self.keypair

    async def calculate_trade_size(self) -> float:
        # exemple ultra simple : 0.05 SOL par trade
        return 0.05

    def get_token_balance(self, token_mint: str) -> float:
        # TODO: ici, il faut implémenter une vraie lecture du solde token
        # Pour le moment, tu peux retourner un montant fixe ou lire via RPC.
        return 1.0
