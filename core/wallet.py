# core/wallet.py
from __future__ import annotations

import json
import os
import logging
from pathlib import Path
from typing import Optional, Union

from solders.keypair import Keypair
from solders.pubkey import Pubkey

log = logging.getLogger("lino.wallet")


class Wallet:
    """
    Wallet compatible solders/solana>=0.28.x
    - Charge un keypair depuis keypair.json (array d'int)
    - Expose:
        - self.keypair (Keypair solders)
        - pubkey() -> str
    """

    def __init__(self, keypair_path: Optional[str] = None):
        self._path = (
            keypair_path
            or os.getenv("KEYPAIR_PATH")
            or str(Path(__file__).resolve().parents[1] / "keypair.json")
        )
        self._keypair: Keypair = self._load_keypair(self._path)

        # petit log compatible avec ton style
        try:
            print(f"[WALLET] Loaded keypair with pubkey: {self.pubkey()}")
        except Exception:
            pass
        log.info("[WALLET] Loaded keypair with pubkey: %s", self.pubkey())

    @property
    def keypair(self) -> Keypair:
        return self._keypair

    def pubkey(self) -> str:
        return str(self._keypair.pubkey())

    def pubkey_obj(self) -> Pubkey:
        return self._keypair.pubkey()

    @staticmethod
    def _load_keypair(path: str) -> Keypair:
        p = Path(path)
        if not p.exists():
            raise RuntimeError(f"KEYPAIR introuvable: {p}")

        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not all(isinstance(x, int) for x in data):
            raise RuntimeError("keypair.json doit être une liste d'entiers (format Solana CLI).")

        raw = bytes(data)

        # Solana CLI => 64 bytes (secret key)
        if len(raw) == 64:
            return Keypair.from_bytes(raw)

        # parfois seed 32 bytes
        if len(raw) == 32:
            return Keypair.from_seed(raw)

        raise RuntimeError(f"Secret key taille inattendue: {len(raw)} (attendu 32 ou 64).")
