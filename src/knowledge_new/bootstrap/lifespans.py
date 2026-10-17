import sys
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from typing import Literal

import settings
from infrastructure.graphrag.availability import detect_graphrag_availability
from infrastructure.processing_run import set_process_pool
from loguru import logger

__all__ = ["get_lifespans"]

_lifespans: dict[Literal["on_startup", "on_shutdown"], list[Callable]] = defaultdict(list)


def get_lifespans(type: Literal["on_startup", "on_shutdown"], /) -> list[Callable]:
    return _lifespans[type]


def on_startup(fn: Callable):
    _lifespans["on_startup"].append(fn)
    return fn


def on_shutdown(fn: Callable):
    _lifespans["on_shutdown"].append(fn)
    return fn


@on_startup
def configure_logging():
    # loguru's default handler prints every frame's variable values in tracebacks,
    # which writes the caller's provider keys to the log whenever an embedder call fails.
    logger.configure(handlers=[{"sink": sys.stderr, "diagnose": False}])


@on_startup
def init_process_pool():
    process_pool = ProcessPoolExecutor(settings.MAX_PROCESS_WORKERS)
    set_process_pool(process_pool)


@on_startup
def check_graphrag_availability():
    if not detect_graphrag_availability():
        logger.warning(
            "AVX2 not detected on this CPU: GraphRAG is unavailable. "
            "GraphRAG endpoints return HTTP 503."
        )
