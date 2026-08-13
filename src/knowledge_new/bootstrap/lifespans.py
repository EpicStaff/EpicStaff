import asyncio
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from typing import Literal

from infrastructure.processing_run import set_process_pool
from presentation.handlers import IndexHandler, PrechunkHandler, SearchHandler
from presentation.handlers.cancel_handler import CancelHandler
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


@on_startup
async def start_handlers():
    broker = brokers.RedisPubSubBroker(settings.BROKER_DNS)
    storage = storages.RedisStorage(settings.STORAGE_DNS)
    producer = Producer(broker, storage)
    consumer = Consumer(broker, storage)
    handlers = [PrechunkHandler, IndexHandler, SearchHandler, CancelHandler]
    for handler in handlers:
        task = asyncio.create_task(handler(producer, consumer).run())
        _handler_tasks.add(task)
        task.add_done_callback(_handler_tasks.discard)


@on_shutdown
async def shut_handlers():
    for task in _handler_tasks:
        task.cancel()
    await asyncio.gather(*_handler_tasks)
