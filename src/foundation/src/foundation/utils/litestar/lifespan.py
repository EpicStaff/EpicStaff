"""Register Litestar startup and shutdown hooks."""

from collections import defaultdict
from typing import Literal

from litestar.types import LifespanHook

__all__ = ["get_shutdowns", "get_startups", "on_shutdown", "on_startup"]

_lifespans: dict[Literal["on_startup", "on_shutdown"], list[LifespanHook]] = defaultdict(list)


def get_startups() -> list[LifespanHook]:
    """Return the registered startup hooks."""
    return _lifespans["on_startup"]


def get_shutdowns() -> list[LifespanHook]:
    """Return the registered shutdown hooks."""
    return _lifespans["on_shutdown"]


def on_startup(fn: LifespanHook):
    """Register the decorated function as a startup hook."""
    _lifespans["on_startup"].append(fn)
    return fn


def on_shutdown(fn: LifespanHook):
    """Register the decorated function as a shutdown hook."""
    _lifespans["on_shutdown"].append(fn)
    return fn
