import time
from typing import Dict, Any

from core.dev_profiler import DevProfiler


class CandidatePipeline:
    """
    Décide quoi faire d’un token pump.fun.
    """

    def __init__(self):
        self.dev_profiler = DevProfiler()

    def on_new_token(self, evt: Dict[str, Any]) -> str:
        mint = evt.get("mint")
        dev = evt.get("creator")
        created_ts = float(evt.get("created_ts") or 0.0)

        if not mint or not dev or created_ts <= 0:
            return "IGNORE"

        now = time.time()
        age = now - created_ts

        # update dev stats
        self.dev_profiler.update_on_new_token(dev)

        if not self.dev_profiler.allow(dev):
            return "IGNORE_DEV"

        # ultra early sniper
        if age <= 10:
            return "SNIPER_EARLY"

        # early sniper
        if age <= 60:
            return "SNIPER"

        return "WATCH"
