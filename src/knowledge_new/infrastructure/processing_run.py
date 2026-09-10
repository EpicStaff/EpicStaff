import asyncio
import functools
import importlib
from collections.abc import Awaitable, Callable
from concurrent.futures.process import ProcessPoolExecutor

__all__ = ["get_process_pool", "run_in_process", "set_process_pool"]


_process_pool: ProcessPoolExecutor | None = None
_registry: dict[tuple[str, str], Callable] = {}


def get_process_pool() -> ProcessPoolExecutor | None:
    return _process_pool


def set_process_pool(pool: ProcessPoolExecutor | None, /):
    global _process_pool
    _process_pool = pool


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
    """
    key = (fn.__module__, fn.__qualname__)
    _registry[key] = fn

    @functools.wraps(fn)
    async def wrap(*args, **kwargs):
        if (pool := get_process_pool()) is not None:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(pool, _invoke, key, args, kwargs)
        return fn(*args, **kwargs)

    return wrap
