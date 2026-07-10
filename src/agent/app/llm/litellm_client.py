"""
LiteLLMClient: concrete ``LLMClient`` backed by LiteLLM Router.

Composes ``RouterPool`` (per-deployment rpm enforcement) and ``RetryPolicy``
(exponential backoff on transient errors).  Normalizes LiteLLM streaming
chunks into the ``LLMChunk`` schema consumed by ``AgentLoop``.

Default max-retry count is read from ``AGENT_DEFAULT_MAX_RETRIES`` env var via
``settings.load_settings()`` on first need; override via the ``retry`` param.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

from loguru import logger

from app.llm.client import LLMChunk, LLMClient, ToolCallFragment
from app.llm.retry import RetryPolicy
from app.llm.router_pool import RouterPool, get_router_pool
from app.logging_utils import redact

_STRIPPED_MODEL_CONFIG_KEYS = frozenset(
    {"model", "api_key", "base_url", "api_version", "max_retry_limit", "max_rpm"}
)


def _cached_prompt_tokens(data: dict) -> int:
    """Extract prompt-cache READ tokens from a normalized usage dict.

    OpenAI-style: nested under ``prompt_tokens_details.cached_tokens``, which
    may still be an object (dict/SimpleNamespace/pydantic model) depending on
    how the caller normalized ``usage``. Anthropic-style responses expose a
    top-level ``cache_read_input_tokens`` fallback instead.
    """
    details = data.get("prompt_tokens_details")

    if details is not None and not isinstance(details, dict):
        details = (
            details.model_dump() if hasattr(details, "model_dump") else vars(details)
        )

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


def _kwargs_for_acompletion(model_config: dict) -> dict:
    """Strip Router-owned and runtime keys from model_config before forwarding."""
    return {
        k: v for k, v in model_config.items() if k not in _STRIPPED_MODEL_CONFIG_KEYS
    }


def _default_max_retries() -> int:
    from settings import load_settings

    return load_settings().agent_default_max_retries


class LiteLLMClient(LLMClient):
    """``LLMClient`` implementation that routes calls through ``litellm.Router``.

    ``retry`` and ``pool`` may be injected for testing; ``None`` means resolve
    the process-singleton at call time so construction is cheap.
    """

    def __init__(
        self,
        retry: RetryPolicy | None = None,
        pool: RouterPool | None = None,
    ) -> None:
        self._retry = retry
        self._pool = pool

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
        assert stream is True, "LiteLLMClient only supports streaming mode"
        return self._stream(messages, tools, model_config, runtime_config)

    async def _stream(
        self,
        messages: list[dict],
        tools: list,
        model_config: dict,
        runtime_config: dict | None,
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

        pool = self._pool or get_router_pool()
        router = await pool.get(
            model=model_config["model"], model_config=model_config, rpm=rpm
        )
        synthetic_model = router.model_list[0]["model_name"]

        retry = self._retry or RetryPolicy(max_retries=_default_max_retries())

        if runtime_max_retries is not None and runtime_max_retries != retry.max_retries:
            retry = retry.with_max_retries(runtime_max_retries)

        extra_kwargs = _kwargs_for_acompletion(model_config)

        async def _call():
            return await router.acompletion(
                model=synthetic_model,
                messages=messages,
                stream=True,
                tools=litellm_tools,
                stream_options={"include_usage": True},
                **extra_kwargs,
            )

        _model = model_config.get("model")
        _synthetic = synthetic_model
        _msg_count = len(messages)
        _tool_count = len(litellm_tools or [])
        logger.opt(lazy=True).debug(
            "litellm request model={} synthetic={} messages={} tools={} kwargs={}",
            lambda: _model,
            lambda: _synthetic,
            lambda: _msg_count,
            lambda: _tool_count,
            lambda: redact(extra_kwargs),
        )
        response_stream = await retry.aretry(_call)

        tc_map: dict[int, dict] = {}

        async for chunk in response_stream:
            usage = getattr(chunk, "usage", None)

            if usage:
                usage_data = _usage_dict(usage)
                logger.debug("litellm usage={}", usage_data)
                yield LLMChunk(usage=usage_data)

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
                    tool_id = tc.id

                    if tool_id is None:
                        # Provider sent no id on the first fragment — synthesize one.
                        tool_id = f"call_{uuid.uuid4().hex[:8]}"

                    tc_map[idx] = {"id": tool_id, "name": tc.function.name}

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
