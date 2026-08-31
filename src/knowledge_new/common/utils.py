import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "make_key",
    "run_async_to_sync",
    "utcnow",
]


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_key(*values: Any) -> str:
    """Join `values` into a colon-delimited key, in order."""
    return ":".join(str(v) for v in values)


def run_async_to_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()
