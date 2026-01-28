# core/async_runner.py
from __future__ import annotations

import asyncio
import threading
from typing import Any, Coroutine, Optional


class AsyncRunner:
    """
    Garde UN event loop vivant dans un thread.
    Permet d'exécuter des coroutines depuis du code sync sans recréer/fermer le loop.
    """

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

        def _thread_main() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=_thread_main, daemon=True)
        self._thread.start()
        self._ready.wait()

    def run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        if not self._loop:
            raise RuntimeError("AsyncRunner loop not started")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()

    def stop(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=2)
