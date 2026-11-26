from collections import defaultdict
from collections.abc import Callable
from importlib import import_module
from importlib.metadata import distributions
from typing import Literal

from infrastructure.naive.chunkers.strategies.token_chunker import load_token_encoding
from infrastructure.processing_run import (
    create_process_pool,
    get_process_pool,
    set_process_pool,
)
from infrastructure.token_estimation import warm_up_token_counter
from loguru import logger

__all__ = ["get_lifespans"]

# The factories import these lazily; importing them at startup moves the cost off the
# first request.
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
    set_process_pool(create_process_pool())


@on_shutdown
def close_process_pool():
    # stop, not close: close would let a running extraction hold shutdown for up
    # to KNOWLEDGE_PROCESS_TIMEOUT.
    # Accepted: with no pool, an extraction reached during shutdown runs inline on the
    # event loop, bounded only by the container stop grace period.
    if (process_pool := get_process_pool()) is not None:
        set_process_pool(None)
        process_pool.stop()
        process_pool.join()


@on_startup
def log_lancedb_build():
    """Name the LanceDB wheel this process runs, for support tickets from old hosts.

    `lancedb-compat` runs on any x86_64 CPU; plain `lancedb` needs AVX2 on x86_64.
    Which one is installed is decided per platform in pyproject.toml and asserted in
    the Dockerfile; this line shows it in the log of a running deployment.
    """
    # Diagnostic only: a failed lookup must not abort boot.
    try:
        builds = sorted(
            f"{distribution.metadata['Name']} {distribution.version}"
            for distribution in distributions()
            if distribution.metadata["Name"].startswith("lancedb")
        )
        logger.info("LanceDB build: {}", ", ".join(builds) or "none")
    except Exception as error:
        logger.warning("LanceDB build lookup failed: {}", error)


# The warm-up hooks below only move first-request latency to startup. The catch is
# deliberately broad: a failed warm-up must never abort boot, and the lazy path
# retries on first use (functools.cache does not cache exceptions).


@on_startup
def preload_graphrag_modules():
    """Move first-request latency to startup by importing the graphrag modules."""
    try:
        for module_name in _GRAPHRAG_MODULES:
            import_module(module_name)
    except Exception as error:
        logger.warning("GraphRAG module preload failed, will import lazily: {}", error)


@on_startup
def preload_token_chunker_tokenizer():
    """Move first-request latency to startup by loading the token chunker's encoding."""
    try:
        load_token_encoding()
    except Exception as error:
        logger.warning("Token chunker encoding preload failed, will load lazily: {}", error)


@on_startup
def preload_token_counter():
    """Move first-request latency to startup by warming litellm's token counter."""
    try:
        warm_up_token_counter()
    except Exception as error:
        logger.warning("Token counter warm-up failed, will load lazily: {}", error)
