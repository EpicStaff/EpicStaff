"""
Unit tests for LiteLLMClient.

Router.acompletion is patched via an injected RouterPool so no real LLM
calls are made.  Streaming chunks are built with SimpleNamespace to match
the attribute-access pattern LiteLLMClient uses.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest
from app.llm.client import LLMChunk
from app.llm.litellm_client import LiteLLMClient
from app.llm.retry import RetryPolicy
from app.llm.router_pool import RouterPool
from app.tools.registry import ToolSpec

# ---------------------------------------------------------------------------
# Chunk builders
# ---------------------------------------------------------------------------


def _tc(index: int, tc_id: str | None, name: str | None, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        id=tc_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _chunk(
    content: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str | None = None,
    usage: dict | None = None,
) -> SimpleNamespace:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    chunk = SimpleNamespace(choices=[choice])
    chunk.usage = SimpleNamespace(**usage) if usage else None
    return chunk


async def _aiter(items):
    for item in items:
        yield item


def make_pool_with_router(router: MagicMock) -> RouterPool:
    """Return a RouterPool stub that always returns ``router``."""
    pool = MagicMock(spec=RouterPool)
    pool.get = AsyncMock(return_value=router)
    return pool


def make_router(chunks: list) -> MagicMock:
    """Return a Router mock whose acompletion returns an async iterator of chunks."""
    router = MagicMock()
    router.model_list = [{"model_name": "synth-model-001"}]
    router.acompletion = AsyncMock(return_value=_aiter(chunks))
    return router


async def collect(client: LiteLLMClient, messages, tools, model_config, **kw) -> list[LLMChunk]:
    chunks = []
    async for chunk in client.chat(messages, tools, model_config, stream=True, **kw):
        chunks.append(chunk)
    return chunks


MODEL_CONFIG = {"model": "gpt-4o", "api_key": "sk-test"}
MESSAGES = [{"role": "user", "content": "hello"}]


# ---------------------------------------------------------------------------
# Tests — plain text streaming
# ---------------------------------------------------------------------------


async def test_plain_text_chunks_yielded():
    """Text deltas produce one LLMChunk(delta_text=...) each; finish_reason at end."""
    chunks_in = [
        _chunk(content="Hello"),
        _chunk(content=" world"),
        _chunk(finish_reason="stop"),
    ]
    router = make_router(chunks_in)
    pool = make_pool_with_router(router)

    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
    result = await collect(client, MESSAGES, [], MODEL_CONFIG)

    text_chunks = [c for c in result if c.delta_text]
    assert [c.delta_text for c in text_chunks] == ["Hello", " world"]

    finish_chunks = [c for c in result if c.finish_reason]
    assert len(finish_chunks) == 1
    assert finish_chunks[0].finish_reason == "stop"


# ---------------------------------------------------------------------------
# Tests — tool-call fragments
# ---------------------------------------------------------------------------


async def test_single_tool_call_fragments_have_stable_id_and_name():
    """First fragment seeds id+name; subsequent fragments use the seeded values."""
    chunks_in = [
        _chunk(tool_calls=[_tc(0, "call_abc", "get_time", "")]),
        _chunk(tool_calls=[_tc(0, None, None, '{"tz":')]),
        _chunk(tool_calls=[_tc(0, None, None, '"UTC"}')]),
        _chunk(finish_reason="tool_calls"),
    ]
    router = make_router(chunks_in)
    pool = make_pool_with_router(router)

    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
    result = await collect(client, MESSAGES, [], MODEL_CONFIG)

    tc_fragments = [c for c in result if c.tool_call_fragment]
    assert len(tc_fragments) == 3

    for fragment in tc_fragments:
        assert fragment.tool_call_fragment.id == "call_abc"
        assert fragment.tool_call_fragment.name == "get_time"

    assert tc_fragments[0].tool_call_fragment.arguments_delta == ""
    assert tc_fragments[1].tool_call_fragment.arguments_delta == '{"tz":'
    assert tc_fragments[2].tool_call_fragment.arguments_delta == '"UTC"}'


async def test_parallel_tool_calls_routed_by_index():
    """Index 0 and index 1 fragments each carry their own id and name."""
    chunks_in = [
        _chunk(
            tool_calls=[
                _tc(0, "call_a1", "tool_a", ""),
                _tc(1, "call_b1", "tool_b", ""),
            ]
        ),
        _chunk(
            tool_calls=[
                _tc(0, None, None, '{"x":1}'),
                _tc(1, None, None, '{"y":2}'),
            ]
        ),
        _chunk(finish_reason="tool_calls"),
    ]
    router = make_router(chunks_in)
    pool = make_pool_with_router(router)

    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
    result = await collect(client, MESSAGES, [], MODEL_CONFIG)

    tc_fragments = [c for c in result if c.tool_call_fragment]
    a_fragments = [
        f.tool_call_fragment for f in tc_fragments if f.tool_call_fragment.id == "call_a1"
    ]
    b_fragments = [
        f.tool_call_fragment for f in tc_fragments if f.tool_call_fragment.id == "call_b1"
    ]

    assert len(a_fragments) == 2
    assert len(b_fragments) == 2

    assert all(f.name == "tool_a" for f in a_fragments)
    assert all(f.name == "tool_b" for f in b_fragments)


async def test_synthetic_id_generated_when_none_on_first_fragment():
    """If the first fragment has id=None, a stable synthetic id is generated."""
    chunks_in = [
        _chunk(tool_calls=[_tc(0, None, "mystery_tool", "")]),
        _chunk(tool_calls=[_tc(0, None, None, '{"k":"v"}')]),
        _chunk(finish_reason="tool_calls"),
    ]
    router = make_router(chunks_in)
    pool = make_pool_with_router(router)

    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
    result = await collect(client, MESSAGES, [], MODEL_CONFIG)

    tc_fragments = [c.tool_call_fragment for c in result if c.tool_call_fragment]
    assert len(tc_fragments) == 2

    synth_id = tc_fragments[0].id
    assert synth_id.startswith("call_")
    assert len(synth_id) == len("call_") + 8

    assert tc_fragments[1].id == synth_id


# ---------------------------------------------------------------------------
# Tests — tool list transformation
# ---------------------------------------------------------------------------


async def test_tools_transformed_to_litellm_format():
    """ToolSpec list is transformed to {"type": "function", "function": {...}} shape."""
    spec = ToolSpec(
        name="my_tool",
        description="does stuff",
        parameters_schema={"type": "object", "properties": {}},
    )

    recorded_calls = []
    router = MagicMock()
    router.model_list = [{"model_name": "synth-model-001"}]

    async def capturing_acompletion(**kwargs):
        recorded_calls.append(kwargs)
        return _aiter([_chunk(content="ok"), _chunk(finish_reason="stop")])

    router.acompletion = capturing_acompletion
    pool = make_pool_with_router(router)

    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
    await collect(client, MESSAGES, [spec], MODEL_CONFIG)

    assert len(recorded_calls) == 1
    tools_arg = recorded_calls[0]["tools"]
    assert tools_arg == [
        {
            "type": "function",
            "function": {
                "name": "my_tool",
                "description": "does stuff",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


async def test_empty_tools_passes_none():
    """Empty tools list passes tools=None to acompletion."""
    recorded_calls = []
    router = MagicMock()
    router.model_list = [{"model_name": "synth-model-001"}]

    async def capturing_acompletion(**kwargs):
        recorded_calls.append(kwargs)
        return _aiter([_chunk(finish_reason="stop")])

    router.acompletion = capturing_acompletion
    pool = make_pool_with_router(router)

    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
    await collect(client, MESSAGES, [], MODEL_CONFIG)

    assert recorded_calls[0]["tools"] is None


# ---------------------------------------------------------------------------
# Tests — retry integration
# ---------------------------------------------------------------------------


async def test_retryable_error_retried_successfully(monkeypatch):
    """First call raises RateLimitError; second call succeeds. Only success chunks yielded."""

    async def fake_sleep(delay):
        pass

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    call_count = [0]
    success_chunks = [_chunk(content="hi"), _chunk(finish_reason="stop")]

    async def flaky_acompletion(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise litellm.RateLimitError("throttled", llm_provider="openai", model="gpt-4o")
        return _aiter(success_chunks)

    router = MagicMock()
    router.model_list = [{"model_name": "synth-model-001"}]
    router.acompletion = flaky_acompletion
    pool = make_pool_with_router(router)

    policy = RetryPolicy(max_retries=3, base_delay=1.0, max_delay=30.0, jitter=0.0)
    client = LiteLLMClient(retry=policy, pool=pool)
    result = await collect(client, MESSAGES, [], MODEL_CONFIG)

    assert call_count[0] == 2
    text_chunks = [c for c in result if c.delta_text]
    assert len(text_chunks) == 1
    assert text_chunks[0].delta_text == "hi"


async def test_non_retryable_error_raises_immediately(monkeypatch):
    """AuthenticationError is not retried and propagates to the caller."""
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def bad_acompletion(**kwargs):
        raise litellm.AuthenticationError("bad key", llm_provider="openai", model="gpt-4o")

    router = MagicMock()
    router.model_list = [{"model_name": "synth-model-001"}]
    router.acompletion = bad_acompletion
    pool = make_pool_with_router(router)

    policy = RetryPolicy(max_retries=3)
    client = LiteLLMClient(retry=policy, pool=pool)

    with pytest.raises(litellm.AuthenticationError):
        await collect(client, MESSAGES, [], MODEL_CONFIG)

    assert slept == []


async def test_runtime_config_max_retry_limit_zero_no_retry(monkeypatch):
    """runtime_config={"max_retry_limit": 0} disables retries even on retryable errors."""
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    call_count = [0]

    async def always_fails(**kwargs):
        call_count[0] += 1
        raise litellm.RateLimitError("throttled", llm_provider="openai", model="gpt-4o")

    router = MagicMock()
    router.model_list = [{"model_name": "synth-model-001"}]
    router.acompletion = always_fails
    pool = make_pool_with_router(router)

    client = LiteLLMClient(retry=RetryPolicy(max_retries=5), pool=pool)

    with pytest.raises(litellm.RateLimitError):
        await collect(
            client,
            MESSAGES,
            [],
            MODEL_CONFIG,
            runtime_config={"max_retry_limit": 0},
        )

    assert call_count[0] == 1
    assert slept == []


async def test_runtime_config_max_rpm_passed_to_pool():
    """runtime_config={"max_rpm": 60} is forwarded as rpm to pool.get."""
    captured_rpm = []

    async def capturing_get(model, model_config, rpm):
        captured_rpm.append(rpm)
        router = MagicMock()
        router.model_list = [{"model_name": "synth-model-001"}]
        router.acompletion = AsyncMock(return_value=_aiter([_chunk(finish_reason="stop")]))
        return router

    pool = MagicMock(spec=RouterPool)
    pool.get = capturing_get

    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
    await collect(
        client,
        MESSAGES,
        [],
        MODEL_CONFIG,
        runtime_config={"max_rpm": 60},
    )

    assert captured_rpm == [60]


# ---------------------------------------------------------------------------
# Tests — usage chunk
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("chunks_in", "expected"),
    [
        (
            [_chunk(content="hi"), _chunk(finish_reason="stop", usage={"prompt_tokens": 5, "completion_tokens": 3})],
            (5, 3, 8),
        ),
        (
            # A terminal usage-only chunk arrives with no choices.
            [
                _chunk(content="hello"),
                SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14)),
                _chunk(finish_reason="stop"),
            ],
            (10, 4, 14),
        ),
    ],
    ids=["usage-on-finish-chunk", "usage-only-chunk"],
)
async def test_usage_is_yielded_once(chunks_in, expected):
    router = make_router(chunks_in)

    result = await collect(LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=make_pool_with_router(router)), MESSAGES, [], MODEL_CONFIG)

    (usage_chunk,) = [chunk for chunk in result if chunk.usage is not None]
    usage = usage_chunk.usage
    assert (usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"]) == expected


async def test_stream_options_include_usage_passed_to_acompletion():
    """acompletion is called with stream_options={"include_usage": True}."""
    recorded_calls = []
    router = MagicMock()
    router.model_list = [{"model_name": "synth-model-001"}]

    async def capturing_acompletion(**kwargs):
        recorded_calls.append(kwargs)
        return _aiter([_chunk(finish_reason="stop")])

    router.acompletion = capturing_acompletion
    pool = make_pool_with_router(router)

    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
    await collect(client, MESSAGES, [], MODEL_CONFIG)

    assert recorded_calls[0]["stream_options"] == {"include_usage": True}


# ---------------------------------------------------------------------------
# Tests — cached_prompt_tokens extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("usage", "expected_cached"),
    [
        ({"prompt_tokens_details": {"cached_tokens": 40}}, 40),
        ({"prompt_tokens_details": SimpleNamespace(cached_tokens=25)}, 25),
        # Anthropic reports cache reads as a top-level field.
        ({"cache_read_input_tokens": 15}, 15),
        ({}, 0),
    ],
    ids=["details-dict", "details-object", "anthropic-top-level", "none"],
)
async def test_cached_prompt_tokens_are_read_from_any_provider_shape(usage, expected_cached):
    router = make_router([_chunk(finish_reason="stop", usage={"prompt_tokens": 100, "completion_tokens": 20, **usage})])

    result = await collect(LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=make_pool_with_router(router)), MESSAGES, [], MODEL_CONFIG)

    (usage_chunk,) = [chunk for chunk in result if chunk.usage is not None]
    assert usage_chunk.usage["cached_prompt_tokens"] == expected_cached


# ---------------------------------------------------------------------------
# Tests — total_cost_usd
# ---------------------------------------------------------------------------


async def test_usage_cost_computed_from_mocked_price_map():
    """cost_per_token is called with the REAL model string (never the Router's
    synthetic hash name) and correct token kwargs; total_cost_usd sums the
    two returned costs."""
    chunks_in = [
        _chunk(
            finish_reason="stop",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "cache_read_input_tokens": 15,
            },
        ),
    ]
    router = make_router(chunks_in)
    pool = make_pool_with_router(router)

    with patch("app.llm.litellm_client.litellm.cost_per_token") as cost_per_token:
        cost_per_token.return_value = (0.001, 0.002)

        client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
        result = await collect(client, MESSAGES, [], MODEL_CONFIG)

    usage_chunks = [c for c in result if c.usage is not None]
    assert len(usage_chunks) == 1
    assert usage_chunks[0].usage["total_cost_usd"] == pytest.approx(0.003)

    cost_per_token.assert_called_once_with(
        model="gpt-4o",
        prompt_tokens=100,
        completion_tokens=20,
        cache_read_input_tokens=15,
    )


async def test_usage_cost_defaults_to_zero_when_price_lookup_raises():
    """Unmapped/self-hosted models raise inside litellm; swallowed to 0.0 and
    the stream still completes."""
    chunks_in = [
        _chunk(content="hi"),
        _chunk(finish_reason="stop", usage={"prompt_tokens": 5, "completion_tokens": 3}),
    ]
    router = make_router(chunks_in)
    pool = make_pool_with_router(router)

    with patch("app.llm.litellm_client.litellm.cost_per_token") as cost_per_token:
        cost_per_token.side_effect = ValueError("unmapped model")

        client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
        result = await collect(client, MESSAGES, [], MODEL_CONFIG)

    usage_chunks = [c for c in result if c.usage is not None]
    assert len(usage_chunks) == 1
    assert usage_chunks[0].usage["total_cost_usd"] == 0.0

    text_chunks = [c for c in result if c.delta_text]
    assert text_chunks[0].delta_text == "hi"


# ---------------------------------------------------------------------------
# Tests — per-config token prices
# ---------------------------------------------------------------------------

UNPRICED_MODEL = "openai/epicstaff-test-gateway-model-without-price"
PRICED_MODEL_CONFIG = {
    "model": UNPRICED_MODEL,
    "api_key": "sk-test",
    "input_cost_per_token": 0.001,
    "output_cost_per_token": 0.002,
}


async def test_usage_cost_uses_the_config_prices_when_both_are_set():
    """An unpriced model gets its cost from the config; cached prompt tokens are
    already inside prompt_tokens and billed once, at the input price."""
    chunks_in = [
        _chunk(
            finish_reason="stop",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_tokens_details": {"cached_tokens": 40},
            },
        ),
    ]
    pool = make_pool_with_router(make_router(chunks_in))

    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
    result = await collect(client, MESSAGES, [], PRICED_MODEL_CONFIG)

    usage_chunks = [c for c in result if c.usage is not None]
    assert usage_chunks[0].usage["total_cost_usd"] == pytest.approx(100 * 0.001 + 20 * 0.002)


async def test_usage_cost_prefers_the_config_prices_over_the_price_map():
    chunks_in = [
        _chunk(finish_reason="stop", usage={"prompt_tokens": 10, "completion_tokens": 5}),
    ]
    pool = make_pool_with_router(make_router(chunks_in))
    model_config = {**PRICED_MODEL_CONFIG, "model": "openai/gpt-4o"}

    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
    result = await collect(client, MESSAGES, [], model_config)

    usage_chunks = [c for c in result if c.usage is not None]
    assert usage_chunks[0].usage["total_cost_usd"] == pytest.approx(10 * 0.001 + 5 * 0.002)


@pytest.mark.parametrize(
    "prices",
    [{"input_cost_per_token": 0.001}, {"output_cost_per_token": 0.002}],
    ids=["input-only", "output-only"],
)
async def test_usage_cost_falls_back_to_the_price_map_without_both_prices(prices):
    chunks_in = [
        _chunk(finish_reason="stop", usage={"prompt_tokens": 10, "completion_tokens": 5}),
    ]
    pool = make_pool_with_router(make_router(chunks_in))
    model_config = {"model": "openai/gpt-4o", "api_key": "sk-test", **prices}

    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
    result = await collect(client, MESSAGES, [], model_config)

    prompt_cost, completion_cost = litellm.cost_per_token(
        model="openai/gpt-4o", prompt_tokens=10, completion_tokens=5
    )
    usage_chunks = [c for c in result if c.usage is not None]
    assert usage_chunks[0].usage["total_cost_usd"] == pytest.approx(prompt_cost + completion_cost)
    assert usage_chunks[0].usage["total_cost_usd"] > 0


async def test_unpriced_model_without_config_prices_costs_zero():
    chunks_in = [
        _chunk(finish_reason="stop", usage={"prompt_tokens": 10, "completion_tokens": 5}),
    ]
    pool = make_pool_with_router(make_router(chunks_in))

    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
    result = await collect(client, MESSAGES, [], {"model": UNPRICED_MODEL, "api_key": "sk-test"})

    usage_chunks = [c for c in result if c.usage is not None]
    assert usage_chunks[0].usage["total_cost_usd"] == 0.0


async def test_token_prices_are_not_forwarded_to_acompletion():
    recorded_calls = []
    router = MagicMock()
    router.model_list = [{"model_name": "synth-model-001"}]

    async def capturing_acompletion(**kwargs):
        recorded_calls.append(kwargs)
        return _aiter([_chunk(finish_reason="stop")])

    router.acompletion = capturing_acompletion
    pool = make_pool_with_router(router)

    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=pool)
    await collect(client, MESSAGES, [], {**PRICED_MODEL_CONFIG, "temperature": 0.3})

    assert "input_cost_per_token" not in recorded_calls[0]
    assert "output_cost_per_token" not in recorded_calls[0]
    assert recorded_calls[0]["temperature"] == 0.3
