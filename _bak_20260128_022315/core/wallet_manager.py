from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List

from config.settings import WALLETS, DEFAULT_MAX_POSITIONS_PER_WALLET


@dataclass
class ManagedWallet:
    """
    Wallet logique (MAIN, ALT1, ALT2…).

    Pour l'instant ils pointent tous vers la même keypair réelle
    mais chacun a sa propre limite de positions.
    """
    name: str
    max_positions: int


class WalletManager:
    """
    Gère la répartition des positions entre les wallets logiques.

    - charge la liste des wallets depuis settings.WALLETS
    - calcule combien de positions chaque wallet a déjà
    - choisit le prochain wallet dispo pour un nouvel achat
    """

    def __init__(self) -> None:
        self.wallets: List[ManagedWallet] = []

        for i, w in enumerate(WALLETS):
            name = w.get("name", f"W{i}")
            max_pos = w.get("max_positions", DEFAULT_MAX_POSITIONS_PER_WALLET)
            if max_pos <= 0:
                # wallet logique désactivé
                continue
            self.wallets.append(ManagedWallet(name=name, max_positions=max_pos))

        self._rr_index: int = 0  # round-robin index

    # ---------------------------------------------------------
    # Helper : compter les positions ouvertes par wallet
    # ---------------------------------------------------------
    def _count_positions_by_wallet(self, positions: Dict[str, Any]) -> Dict[str, int]:
        counts = {w.name: 0 for w in self.wallets}

        if isinstance(positions, dict):
            for pos in positions.values():
                wname = pos.get("wallet")
                if wname in counts:
                    counts[wname] += 1

        return counts

    # ---------------------------------------------------------
    # Choisir le prochain wallet dispo pour un nouveau BUY
    # ---------------------------------------------------------
    def pick_wallet_for_new_position(self, positions: Dict[str, Any]) -> ManagedWallet | None:
        """
        Retourne un ManagedWallet dispo (sous sa limite de positions),
        ou None si tous les wallets sont pleins.
        """
        if not self.wallets:
            return None

        counts = self._count_positions_by_wallet(positions)
        n = len(self.wallets)

        for offset in range(n):
            idx = (self._rr_index + offset) % n
            w = self.wallets[idx]
            if counts.get(w.name, 0) < w.max_positions:
                # on avance le pointeur round-robin
                self._rr_index = (idx + 1) % n
                return w

        # tous les wallets sont pleins
        return None
