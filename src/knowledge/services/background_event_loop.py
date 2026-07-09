import asyncio
import threading
from collections.abc import Coroutine
from typing import Any


class BackgroundEventLoop:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run[T](self, coro: Coroutine[Any, Any, T]) -> T:
        if not asyncio.iscoroutine(coro):
            raise TypeError(f'a coroutine is expected, but got {coro!r}')

        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def stop(self):
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._loop.close()


background_loop = BackgroundEventLoop()
