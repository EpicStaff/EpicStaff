"""
LiteLLMClient: concrete ``LLMClient`` backed by ``litellm.acompletion``.

Composes ``ConcurrencyLimiter`` (``max_rpm`` as a per-deployment in-flight cap)
and ``RetryPolicy`` (exponential backoff on transient errors). Normalizes LiteLLM
streamed chunks or a single non-streamed response into the ``LLMChunk`` schema
consumed by ``AgentLoop``.

Default max-retry count is read from ``AGENT_DEFAULT_MAX_RETRIES`` env var via
``settings.load_settings()`` on first need; override via the ``retry`` param.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import litellm
from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper
from loguru import logger

from app.llm.client import LLMChunk, LLMClient, ToolCallFragment
from app.llm.concurrency_limiter import ConcurrencyLimiter, get_concurrency_limiter
from app.llm.retry import RetryPolicy
from app.logging_utils import redact

_STRIPPED_MODEL_CONFIG_KEYS = frozenset({"max_retry_limit", "max_rpm"})


def _cached_prompt_tokens(data: dict) -> int:
    """Extract prompt-cache READ tokens from a normalized usage dict.

    OpenAI-style: nested under ``prompt_tokens_details.cached_tokens``, which
    may still be an object (dict/SimpleNamespace/pydantic model) depending on
    how the caller normalized ``usage``. Anthropic-style responses expose a
    top-level ``cache_read_input_tokens`` fallback instead.
    """
    details = data.get("prompt_tokens_details")

    if details is not None and not isinstance(details, dict):
        details = details.model_dump() if hasattr(details, "model_dump") else vars(details)

    if details:
        cached = details.get("cached_tokens")

        if cached:
            return int(cached)

    # Anthropic-style top-level fallback when details are absent.
    return int(data.get("cache_read_input_tokens") or 0)


def _usage_dict(usage) -> dict:
    """Normalize a litellm Usage object / SimpleNamespace / dict to plain token counts."""
    if isinstance(usage, dict):
        data = usage
    elif hasattr(usage, "model_dump"):
        data = usage.model_dump()
    else:
        data = vars(usage)

    prompt = int(data.get("prompt_tokens") or 0)
    completion = int(data.get("completion_tokens") or 0)
    total = int(data.get("total_tokens") or (prompt + completion))
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cached_prompt_tokens": _cached_prompt_tokens(data),
    }


def _usage_cost_usd(model: str, usage: dict) -> float:
    """Best-effort USD cost for a normalized usage dict via litellm's price map.

    ``model`` must be the real ``provider/model`` string; litellm's price map
    only recognizes real model identifiers. Unmapped or self-hosted models raise
    inside litellm; swallowed to 0.0 since cost is a display-only value, never billing truth.
    """
    try:
        prompt_cost, completion_cost = litellm.cost_per_token(
            model=model,
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            cache_read_input_tokens=usage["cached_prompt_tokens"],
        )
        return prompt_cost + completion_cost

    except Exception as error:
        logger.debug("cost lookup failed model={} error={}", model, error)
        return 0.0


def _synthetic_call_id() -> str:
    """Id for a tool call the provider sent without one."""
    return f"call_{uuid.uuid4().hex[:8]}"


def _usage_chunk(usage, model: str) -> LLMChunk:
    usage_data = _usage_dict(usage)
    usage_data["total_cost_usd"] = _usage_cost_usd(model, usage_data)
    logger.debug("litellm usage={}", usage_data)
    return LLMChunk(usage=usage_data)


def _response_chunks(response, model: str) -> list[LLMChunk]:
    """Split a non-streamed response into the chunks the stream path would yield."""
    chunks: list[LLMChunk] = []
    finish_reason = None

    # The Responses API bridge returns text and tool calls as separate choices.
    for choice in response.choices or []:
        message = choice.message
        finish_reason = choice.finish_reason or finish_reason

        if message.content:
            chunks.append(LLMChunk(delta_text=message.content))

        for tool_call in message.tool_calls or []:
            chunks.append(
                LLMChunk(
                    tool_call_fragment=ToolCallFragment(
                        id=tool_call.id or _synthetic_call_id(),
                        name=tool_call.function.name or "",
                        arguments_delta=tool_call.function.arguments or "",
                    )
                )
            )

    usage = getattr(response, "usage", None)

    if usage:
        chunks.append(_usage_chunk(usage, model))

    if finish_reason:
        logger.debug("litellm finish_reason={}", finish_reason)
        chunks.append(LLMChunk(finish_reason=finish_reason))

    return chunks


def _kwargs_for_acompletion(model_config: dict) -> dict:
    """Strip runtime-only keys from model_config before forwarding."""
    return {k: v for k, v in model_config.items() if k not in _STRIPPED_MODEL_CONFIG_KEYS}


def _default_max_retries() -> int:
    import settings

    return settings.AGENT_DEFAULT_MAX_RETRIES


class LiteLLMClient(LLMClient):
    """``LLMClient`` implementation that calls ``litellm.acompletion`` directly.

    ``retry`` and ``limiter`` may be injected for testing; ``None`` means the
    default retry policy and the process-wide limiter.
    """

    def __init__(
        self,
        retry: RetryPolicy | None = None,
        limiter: ConcurrencyLimiter | None = None,
    ) -> None:
        self._retry = retry
        self._limiter = limiter or get_concurrency_limiter()

    def chat(
        self,
        messages: list[dict],
        tools: list,
        model_config: dict,
        *,
        stream: bool,
        runtime_config: dict | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """Return an async generator of normalized ``LLMChunk`` objects."""
        return self._chat(messages, tools, model_config, runtime_config, stream)

    async def _chat(
        self,
        messages: list[dict],
        tools: list,
        model_config: dict,
        runtime_config: dict | None,
        stream: bool,
    ) -> AsyncIterator[LLMChunk]:
        litellm_tools = (
            [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters_schema,
                    },
                }
                for tool in tools
            ]
            if tools
            else None
        )

        runtime_config = runtime_config or {}
        runtime_max_retries = runtime_config.get("max_retry_limit")
        rpm = runtime_config.get("max_rpm")

        retry = self._retry or RetryPolicy(max_retries=_default_max_retries())

        if runtime_max_retries is not None and runtime_max_retries != retry.max_retries:
            retry = retry.with_max_retries(runtime_max_retries)

        extra_kwargs = _kwargs_for_acompletion(model_config)

        if stream:
            extra_kwargs["stream_options"] = {"include_usage": True}

        async def _call():
            # Held only until the response object arrives; a stream is consumed outside the slot.
            async with self._limiter.slot(model_config, rpm):
                response = await litellm.acompletion(
                    messages=messages,
                    stream=stream,
                    tools=litellm_tools,
                    # RetryPolicy owns retries; SDK retries would multiply the attempts.
                    max_retries=0,
                    timeout=litellm.request_timeout,
                    _skip_mcp_handler=True,  # agent handles MCP itself; don't import litellm.proxy stack
                    **extra_kwargs,
                )

            # Some providers open the stream lazily; open it here so connect errors are retried.
            if isinstance(response, CustomStreamWrapper):
                await response.fetch_stream()

            return response

        _model = model_config.get("model")
        _msg_count = len(messages)
        _tool_count = len(litellm_tools or [])
        logger.opt(lazy=True).debug(
            "litellm request model={} stream={} messages={} tools={} kwargs={}",
            lambda: _model,
            lambda: stream,
            lambda: _msg_count,
            lambda: _tool_count,
            lambda: redact(extra_kwargs),
        )
        response = await retry.aretry(_call)

        if not stream:
            for chunk in _response_chunks(response, model_config["model"]):
                yield chunk
            return

        # No caller streams yet (the agent loop uses stream=False); kept for the STREAM-mode chat runner.
        tc_map: dict[int, dict] = {}

        async for chunk in response:
            usage = getattr(chunk, "usage", None)

            if usage:
                yield _usage_chunk(usage, model_config["model"])

            choices = chunk.choices or []

            if not choices:
                continue

            choice = choices[0]
            delta = choice.delta
            finish = choice.finish_reason

            if delta.content:
                yield LLMChunk(delta_text=delta.content)

            for tc in delta.tool_calls or []:
                idx = tc.index

                if idx not in tc_map:
                    tc_map[idx] = {"id": tc.id or _synthetic_call_id(), "name": tc.function.name}

                seeded = tc_map[idx]

                yield LLMChunk(
                    tool_call_fragment=ToolCallFragment(
                        id=tc.id or seeded["id"],
                        name=tc.function.name or seeded["name"] or "",
                        arguments_delta=tc.function.arguments or "",
                    )
                )

            if finish:
                logger.debug("litellm finish_reason={}", finish)
                yield LLMChunk(finish_reason=finish)
