import json
import time
from pathlib import Path
from typing import Dict, Any


class DevProfiler:
    """
    Maintient un profil par dev (creator / deployer).
    Stocké en JSON local (dev_db.json).
    """

    def __init__(self, path: str = "dev_db.json"):
        self.path = Path(path)
        self.db: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self.db = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.db = {}

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.db, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get(self, dev: str) -> Dict[str, Any]:
        return self.db.get(
            dev,
            {
                "score": 0,
                "tokens": 0,
                "rugs": 0,
                "blacklisted": False,
                "last_seen": None,
            },
        )

    def update_on_new_token(self, dev: str) -> None:
        p = self.get(dev)
        p["tokens"] = int(p.get("tokens") or 0) + 1
        p["last_seen"] = time.time()
        self.db[dev] = p
        self._save()

    def flag_rug(self, dev: str) -> None:
        p = self.get(dev)
        p["rugs"] = int(p.get("rugs") or 0) + 1
        p["score"] = int(p.get("score") or 0) - 5
        if p["rugs"] >= 2:
            p["blacklisted"] = True
        self.db[dev] = p
        self._save()

    def allow(self, dev: str) -> bool:
        p = self.get(dev)
        if p.get("blacklisted"):
            return False
        if int(p.get("score") or 0) < -5:
            return False
        return True
