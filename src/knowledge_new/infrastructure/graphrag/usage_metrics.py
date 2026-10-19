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

graphrag_llm's metrics processor ignores streamed responses, and every search answer is
streamed. Completion models are therefore swapped for a LiteLLM subclass that asks the
provider to report usage on the stream and adds the final usage chunk to the tally. A
provider that ignores or rejects `include_usage` yields no usage chunk, so its streamed
calls count as zero rather than as an estimate.
"""

import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from domain.usage import UsageTally
from graphrag_llm.completion.completion_factory import register_completion
from graphrag_llm.completion.lite_llm_completion import LiteLLMCompletion
from graphrag_llm.config import MetricsConfig
from graphrag_llm.config.types import LLMProviderType
from graphrag_llm.metrics import MetricsStore, register_metrics_store
from litellm.exceptions import BadRequestError
from loguru import logger

if TYPE_CHECKING:
    from graphrag.config.models.graph_rag_config import GraphRagConfig
    from graphrag_llm.types import LLMCompletionChunk, Metrics

_STORE_TYPE = "rag_usage_tally"
_COMPLETION_TYPE = "rag_usage_litellm"
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


class StreamUsageCompletion(LiteLLMCompletion):
    """LiteLLM completion that adds the usage of streamed responses to the current tally."""

    async def completion_async(self, /, **kwargs: Any) -> Any:
        tally = _current_tally.get()
        if not kwargs.get("stream") or tally is None:
            return await super().completion_async(**kwargs)
        if "stream_options" in kwargs:
            stream = await super().completion_async(**kwargs)
            return _tally_stream_usage(stream, tally)
        try:
            stream = await super().completion_async(
                **kwargs, stream_options={"include_usage": True}
            )
        except BadRequestError:
            # Some gateways and older Azure deployments reject `stream_options`, and an
            # OpenAI-compatible custom api_base is treated as openai, so litellm does not
            # drop it. Retry once without it; the call then counts as zero.
            logger.warning(
                "Provider rejected stream_options; retrying the stream without usage reporting"
            )
            return await super().completion_async(**kwargs)
        return _tally_stream_usage(stream, tally)


async def _tally_stream_usage(
    stream: "AsyncIterator[LLMCompletionChunk]", tally: UsageTally
) -> "AsyncIterator[LLMCompletionChunk]":
    """Pass `stream` through and add its usage to `tally` when it ends.

    Providers may repeat usage on several chunks; each figure is cumulative, so the
    largest one seen is the call's usage. The usage-only chunk that `include_usage`
    makes providers append has no `choices`; it is tallied but not yielded, because
    graphrag reads `chunk.choices[0]` unguarded. Every other chunk is yielded unchanged.

    Usage is recorded when the stream is fully consumed or the wrapper is closed
    explicitly (`aclose()`), which also closes `stream`. An abandoned wrapper is only
    recorded when the garbage collector finalizes it, which may be late.
    """
    prompt_tokens = 0
    completion_tokens = 0
    try:
        async for chunk in stream:
            usage = chunk.usage
            if usage is not None:
                prompt_tokens = max(prompt_tokens, usage.prompt_tokens or 0)
                completion_tokens = max(completion_tokens, usage.completion_tokens or 0)
            if not chunk.choices:
                continue
            yield chunk
    finally:
        with _tally_lock:
            tally.llm_input_tokens += prompt_tokens
            tally.llm_output_tokens += completion_tokens
        close_inner = getattr(stream, "aclose", None)
        if close_inner is not None:
            await close_inner()


register_completion(_COMPLETION_TYPE, StreamUsageCompletion, scope="singleton")


@contextmanager
def track_usage(config: "GraphRagConfig") -> Iterator[UsageTally]:
    """Meter every model of `config` into the yielded tally for the duration of the block.

    Models are only metered if the block's `build_index` instantiates them after this
    call, so enter it before handing `config` to graphrag.
    """
    tally = UsageTally()
    for model_config in config.completion_models.values():
        model_config.metrics = _metrics_config(_COMPLETION_KIND)
        if model_config.type == LLMProviderType.LiteLLM:
            model_config.type = _COMPLETION_TYPE
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
