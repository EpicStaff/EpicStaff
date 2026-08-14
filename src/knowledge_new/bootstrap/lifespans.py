import asyncio
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from typing import Literal

from infrastructure.processing_run import set_process_pool
from settings import settings
from src.shared.communication import Consumer, Producer, brokers, storages

__all__ = ["get_lifespans"]

_lifespans: dict[Literal["on_startup", "on_shutdown"], list[Callable]] = defaultdict(list)
_handler_tasks: set[asyncio.Task] = set()


def get_lifespans(type: Literal["on_startup", "on_shutdown"], /) -> list[Callable]:
    return _lifespans[type]


def on_startup(fn: Callable):
    _lifespans["on_startup"].append(fn)
    return fn


def on_shutdown(fn: Callable):
    _lifespans["on_shutdown"].append(fn)
    return fn


@on_startup
def init_process_pool():
    process_pool = ProcessPoolExecutor(settings.MAX_PROCESS_WORKERS)
    set_process_pool(process_pool)
