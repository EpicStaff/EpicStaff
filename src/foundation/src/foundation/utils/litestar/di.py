"""Register and collect Litestar injectable dependencies."""

from collections.abc import Callable

from litestar.di import Provide

__all__ = ["get_dependencies", "register"]


_dependencies: dict[str, Provide] = {}


def get_dependencies() -> dict[str, Provide]:
    """Return the mapping of registered Litestar dependencies."""
    return _dependencies


def register(
    fn: Callable | None = None,
    /,
    use_cache=False,
    sync_to_thread: bool | None = None,
):
    """Register a function as a Litestar dependency, keyed by its name."""

    def decorator(func: Callable):
        _dependencies[func.__name__] = Provide(
            func,
            use_cache=use_cache,
            sync_to_thread=sync_to_thread,
        )
        return func

    if fn is None:
        return decorator
    return decorator(fn)
