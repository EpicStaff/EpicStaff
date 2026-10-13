from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from importlib import import_module
from typing import Literal

import settings
from infrastructure.graphrag.availability import (
    detect_graphrag_availability,
    is_graphrag_available,
)
from infrastructure.naive.chunkers.strategies.token_chunker import load_gpt2_tokenizer
from infrastructure.processing_run import set_process_pool
from infrastructure.token_estimation import warm_up_token_counter
from loguru import logger

__all__ = ["get_lifespans"]

# Imported lazily by the factories so a CPU without AVX2 never loads graphrag; on a
# capable CPU they are imported at startup instead of during the first request.
_GRAPHRAG_MODULES = (
    "infrastructure.database.repositories.graph",
    "application.orchestrators.indexing.strategies.graph_indexer",
    "application.orchestrators.metrics.strategies.graph_metrics",
    "application.orchestrators.removing.strategies.graph_remover",
    "application.orchestrators.searching.strategies.graph_search",
)

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


# The warm-up hooks below only move first-request latency to startup. The catch is
# deliberately broad: a failed warm-up must never abort boot, and the lazy path
# retries on first use (functools.cache does not cache exceptions).


@on_startup
def preload_graphrag_modules():
    """Move first-request latency to startup by importing the graphrag modules."""
    if not is_graphrag_available():
        return
    try:
        for module_name in _GRAPHRAG_MODULES:
            import_module(module_name)
    except Exception as error:
        logger.warning("GraphRAG module preload failed, will import lazily: {}", error)


@on_startup
def preload_token_chunker_tokenizer():
    """Move first-request latency to startup by loading the GPT-2 tokenizer."""
    try:
        load_gpt2_tokenizer()
    except Exception as error:
        logger.warning("GPT-2 tokenizer preload failed, will load lazily: {}", error)


@on_startup
def preload_token_counter():
    """Move first-request latency to startup by warming litellm's token counter."""
    try:
        warm_up_token_counter()
    except Exception as error:
        logger.warning("Token counter warm-up failed, will load lazily: {}", error)
