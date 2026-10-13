"""Per-run token usage of graphrag's model calls, read from its metrics stores.

graphrag_llm's default metrics store is a process-wide singleton, so it cannot tell
two index runs apart. This module registers its own store type, attaches it to a run's
models, and adds each call's token usage to the tally of the run the call belongs to.
The run is found through a ContextVar, never through the model's config: graphrag_llm
caches models by their config, so anything run-specific in it would leak one cached
model per run. Context reaches the model calls because they run on the run's own
asyncio tasks, which copy the context when created. Only calls that returned a response
with usage are counted: a failed attempt, which the provider may still have billed, is
invisible here.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from domain.usage import UsageTally
from graphrag_llm.config import MetricsConfig
from graphrag_llm.metrics import MetricsStore, register_metrics_store

if TYPE_CHECKING:
    from graphrag.config.models.graph_rag_config import GraphRagConfig
    from graphrag_llm.types import Metrics

_STORE_TYPE = "rag_usage_tally"
_COMPLETION_KIND = "completion"
_EMBEDDING_KIND = "embedding"

_current_tally: ContextVar[UsageTally | None] = ContextVar("rag_usage_tally", default=None)
_tally_lock = threading.Lock()


class TallyMetricsStore(MetricsStore):
    """Adds each model call's token counts to the tally of the run the call is made in."""

    def __init__(self, *, id: str, usage_kind: str, **kwargs: Any) -> None:
        self._id = id
        self._usage_kind = usage_kind

    @property
    def id(self) -> str:
        return self._id

    def update_metrics(self, *, metrics: "Metrics") -> None:
        prompt_tokens = int(metrics.get("prompt_tokens", 0))
        completion_tokens = int(metrics.get("completion_tokens", 0))
        tally = _current_tally.get()
        if tally is None:
            return
        with _tally_lock:
            if self._usage_kind == _EMBEDDING_KIND:
                tally.embedding_tokens += prompt_tokens
            else:
                tally.llm_input_tokens += prompt_tokens
                tally.llm_output_tokens += completion_tokens

    def get_metrics(self) -> "Metrics":
        return {}

    def clear_metrics(self) -> None:
        return


register_metrics_store(_STORE_TYPE, TallyMetricsStore, scope="transient")


@contextmanager
def track_usage(config: "GraphRagConfig") -> Iterator[UsageTally]:
    """Meter every model of `config` into the yielded tally for the duration of the block.

    Models are only metered if the block's `build_index` instantiates them after this
    call, so enter it before handing `config` to graphrag.
    """
    tally = UsageTally()
    for model_config in config.completion_models.values():
        model_config.metrics = _metrics_config(_COMPLETION_KIND)
    for model_config in config.embedding_models.values():
        model_config.metrics = _metrics_config(_EMBEDDING_KIND)
    token = _current_tally.set(tally)
    try:
        yield tally
    finally:
        _current_tally.reset(token)


def _metrics_config(usage_kind: str) -> MetricsConfig:
    # `writer=None` skips graphrag's default log writer, which only reports at exit.
    return MetricsConfig(store=_STORE_TYPE, writer=None, usage_kind=usage_kind)
