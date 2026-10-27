import asyncio
import functools
import importlib
from collections.abc import Awaitable, Callable

import settings
from loguru import logger
from pebble import ProcessPool

__all__ = ["create_process_pool", "get_process_pool", "run_in_process", "set_process_pool"]


_process_pool: ProcessPool | None = None
_registry: dict[tuple[str, str], Callable] = {}


def get_process_pool() -> ProcessPool | None:
    return _process_pool


def set_process_pool(pool: ProcessPool | None, /):
    global _process_pool
    _process_pool = pool


def create_process_pool() -> ProcessPool:
    return ProcessPool(settings.MAX_PROCESS_WORKERS)


def _usable_process_pool() -> ProcessPool | None:
    """Return the installed pool, replacing it first if it has stopped working.

    pebble marks a pool broken for good when a worker dies while no task is
    running (e.g. an idle worker picked by the OOM killer); every later schedule
    would fail until restart. Must not await between check and replace, so two
    concurrent callers on the event loop cannot both rebuild.
    """
    pool = get_process_pool()
    if pool is None or pool.active:
        return pool
    logger.warning("Process pool is broken; replacing it.")
    replacement = create_process_pool()
    set_process_pool(replacement)
    # join() terminates the old pool's surviving workers; it blocks, so run it off the event loop.
    asyncio.get_running_loop().run_in_executor(None, pool.join)
    return replacement


def _invoke(key: tuple[str, str], args, kwargs):
    """Call the function registered under `key`, importing its module if absent.

    Args:
        key: The `(module, qualname)` pair identifying the registered function.
        args: Positional arguments forwarded to the function.
        kwargs: Keyword arguments forwarded to the function.

    Note:
        A fresh worker process starts with an empty registry, so the function's
        module is imported on demand to repopulate it.
    """
    fn = _registry.get(key)
    if fn is None:
        importlib.import_module(key[0])
        fn = _registry[key]
    return fn(*args, **kwargs)


def run_in_process[T](fn: Callable[..., T]) -> Callable[..., Awaitable[T]]:
    """Wrap a sync function so it runs in the process pool when one is set.

    Args:
        fn: The sync function to offload.

    Returns:
        An async wrapper that offloads `fn` to the pool, or calls it directly
        when no pool is set.

    Note:
        `fn` is registered by module and qualified name so worker processes can
        import and look it up; it must be importable at module level.
        An offloaded call that outruns `settings.PROCESS_TIMEOUT` raises
        `TimeoutError`, and one whose worker dies (e.g. OOM-killed) raises
        `pebble.ProcessExpired`; either way only that worker is replaced and the
        pool stays usable. Cancelling the awaiting task cancels the pool future,
        which terminates the worker running the call instead of leaving it busy.
    """
    key = (fn.__module__, fn.__qualname__)
    _registry[key] = fn

    @functools.wraps(fn)
    async def wrap(*args, **kwargs):
        if (pool := _usable_process_pool()) is not None:
            future = pool.schedule(
                _invoke, args=(key, args, kwargs), timeout=settings.PROCESS_TIMEOUT
            )
            return await asyncio.wrap_future(future)
        return fn(*args, **kwargs)

    return wrap
