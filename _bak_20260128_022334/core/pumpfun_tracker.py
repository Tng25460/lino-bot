from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core.pumpfun_mint_resolver import MintResolver


class PumpfunTracker:
    """
    Track les créations pump.fun AVANT mint SPL.
    Clé = creator (dev)

    States:
      - WATCH_PUMPFUN : on a vu le create, mint pas encore dispo
      - ARMED         : mint trouvé -> prêt pour sniper (mais on trade pas ici)
      - BAN_DEV       : dev blacklisté (plus tard)
    """

    def __init__(
        self,
        rpc_http: str = "https://api.mainnet-beta.solana.com",
        db_path: str = "pumpfun_dev_db.json",
        max_age_watch_s: float = 15 * 60,
    ):
        self.db_path = Path(db_path)
        self.max_age_watch_s = float(max_age_watch_s)

        self.resolver = MintResolver(rpc_http=rpc_http, commitment="confirmed")

        # creator -> record
        self.candidates: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.db_path.exists():
            try:
                data = json.loads(self.db_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.candidates = data
            except Exception:
                self.candidates = {}

    def _save(self) -> None:
        try:
            self.db_path.write_text(json.dumps(self.candidates, indent=2), encoding="utf-8")
        except Exception:
            pass

    def on_create(self, evt: Dict[str, Any]) -> str:
        """
        evt attendu:
          {"creator": str, "created_ts": float, "signature": str, "source": "pumpfun", "mint": Optional[str]}
        """
        creator = str(evt.get("creator") or "").strip()
        created_ts = float(evt.get("created_ts") or 0.0)
        sig = str(evt.get("signature") or "").strip()

        if not creator or created_ts <= 0:
            return "IGNORE"

        now = time.time()
        rec = self.candidates.get(creator)

        if not rec:
            rec = {
                "creator": creator,
                "first_seen": created_ts,
                "last_seen": now,
                "nb_creations": 1,
                "status": "WATCH_PUMPFUN",
                "last_sig": sig,
                "mint": None,
                "mint_sig": None,
            }
            self.candidates[creator] = rec
        else:
            rec["last_seen"] = now
            rec["nb_creations"] = int(rec.get("nb_creations") or 0) + 1
            rec["last_sig"] = sig or rec.get("last_sig")
            # on ne downgrade jamais ARMED -> WATCH
            if rec.get("status") not in ("ARMED", "BAN_DEV"):
                rec["status"] = "WATCH_PUMPFUN"

        self._save()
        return str(self.candidates[creator].get("status") or "WATCH_PUMPFUN")

    async def tick_find_mints(self) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Cherche un mint pour les devs en WATCH.
        Retour:
          ("MINT_FOUND", {"creator":..., "mint":..., "age":..., ...}) ou None
        """
        now = time.time()

        # cleanup vieux WATCH
        to_del = []
        for creator, rec in (self.candidates or {}).items():
            st = rec.get("status")
            if st == "WATCH_PUMPFUN":
                first_seen = float(rec.get("first_seen") or 0.0)
                if first_seen > 0 and (now - first_seen) > self.max_age_watch_s:
                    to_del.append(creator)
        for c in to_del:
            self.candidates.pop(c, None)

        # cherche mint pour 1 dev à la fois (évite spam RPC)
        for creator, rec in (self.candidates or {}).items():
            if rec.get("status") != "WATCH_PUMPFUN":
                continue

            mint, mint_sig = await self.resolver.find_mint_for_creator(creator, lookback_limit=25)
            if mint:
                rec["mint"] = mint
                rec["mint_sig"] = mint_sig
                rec["status"] = "ARMED"
                rec["armed_ts"] = time.time()
                self._save()

                age = time.time() - float(rec.get("first_seen") or time.time())
                payload = {
                    "creator": creator,
                    "mint": mint,
                    "age": age,
                    "first_seen": rec.get("first_seen"),
                    "last_sig": rec.get("last_sig"),
                    "mint_sig": mint_sig,
                    "status": "ARMED",
                    "source": "pumpfun",
                }
                return "MINT_FOUND", payload

        self._save()
        return None
