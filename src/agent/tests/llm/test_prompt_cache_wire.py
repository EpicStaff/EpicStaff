"""
Prompt-cache markers on the wire: the agent's model config goes through the real
``LiteLLMClient`` and litellm Router, and only the HTTP transport is replaced, so the
assertions read the JSON body litellm would send to the provider.
"""

from __future__ import annotations

import copy
import json

import httpx
import litellm
import pytest
from app.llm.litellm_client import LiteLLMClient
from app.llm.retry import RetryPolicy
from app.llm.router_pool import RouterPool
from app.loop.agent_loop import _build_model_config
from app.loop.context import AgentContext
from app.tools.registry import ToolSpec
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from shared.models.agent_service import AgentSpec
from shared.models.ai_providers import LLMConfigData, LLMData
from tests.cancellation import never_cancelled
from tests.secret_sealing import agent_cryptographer, seal

EPHEMERAL = {"type": "ephemeral"}

CONVERSATION = [
    {"role": "system", "content": "Your name is Clerk. Follow the instructions."},
    {"role": "system", "content": "[context source: s3]\nreport.pdf (12 KB)"},
    {"role": "user", "content": "What time is it?"},
    {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "toolu_01",
                "type": "function",
                "function": {"name": "get_time", "arguments": '{"zone": "UTC"}'},
            }
        ],
    },
    {"role": "tool", "tool_call_id": "toolu_01", "content": "12:00"},
]

TOOLS = [
    ToolSpec(
        name="get_time",
        description="Return the current time.",
        parameters_schema={"type": "object", "properties": {"zone": {"type": "string"}}},
    )
]

ANTHROPIC_RESPONSE = {
    "id": "msg_01",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-5-5",
    "content": [{"type": "text", "text": "It is noon."}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 20, "output_tokens": 5},
}

OPENAI_RESPONSE = {
    "id": "chatcmpl-01",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4o",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "It is noon."},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
}

RESPONSES_API_RESPONSE = {
    "id": "resp_01",
    "object": "response",
    "created_at": 1,
    "status": "completed",
    "model": "gpt-5.6",
    "output": [
        {
            "type": "message",
            "id": "msg_01",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "It is noon.", "annotations": []}],
        }
    ],
    "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25},
    "parallel_tool_calls": True,
    "tool_choice": "auto",
    "tools": [],
}


@pytest.fixture
def sent_bodies(monkeypatch):
    """Replace litellm's HTTP transport; collect the JSON body of every request."""
    bodies: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if request.url.host == "api.anthropic.com":
            payload = ANTHROPIC_RESPONSE
        elif request.url.path.endswith("/responses"):
            payload = RESPONSES_API_RESPONSE
        else:
            payload = OPENAI_RESPONSE
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        AsyncHTTPHandler,
        "create_async_transport",
        staticmethod(lambda **_: httpx.MockTransport(respond)),
    )
    litellm.in_memory_llm_clients_cache.flush_cache()
    yield bodies
    litellm.in_memory_llm_clients_cache.flush_cache()


def _model_config(provider: str, model: str, *, prompt_caching_enabled: bool) -> dict:
    agent = AgentSpec(
        id=1,
        name="Clerk",
        instructions="Follow the instructions.",
        llm=LLMData(provider=provider, config=LLMConfigData(model=model, api_key=seal("sk-test"))),
        prompt_caching_enabled=prompt_caching_enabled,
    )
    context = AgentContext(
        agent=agent, attachments=[], correlation_id="c", is_cancelled=never_cancelled
    )
    return _build_model_config(context, agent_cryptographer())


async def _send(messages: list[dict], model_config: dict) -> None:
    # The agent loop calls with stream=False.
    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=RouterPool())
    async for _ in client.chat(messages, TOOLS, model_config, stream=False):
        pass


def _count_cache_control(value) -> int:
    if isinstance(value, dict):
        return ("cache_control" in value) + sum(_count_cache_control(item) for item in value.values())
    if isinstance(value, list):
        return sum(_count_cache_control(item) for item in value)
    return 0


def _without_cache_control(value):
    if isinstance(value, dict):
        return {key: _without_cache_control(item) for key, item in value.items() if key != "cache_control"}
    if isinstance(value, list):
        return [_without_cache_control(item) for item in value]
    return value


async def _anthropic_body(sent_bodies: list[dict], *, prompt_caching_enabled: bool) -> dict:
    messages = copy.deepcopy(CONVERSATION)
    await _send(
        messages,
        _model_config("anthropic", "claude-sonnet-5-5", prompt_caching_enabled=prompt_caching_enabled),
    )
    assert messages == CONVERSATION, "the caller's messages were changed"
    return sent_bodies[-1]


async def test_switch_on_marks_the_system_prompt_and_the_last_message_only(sent_bodies):
    body = await _anthropic_body(sent_bodies, prompt_caching_enabled=True)

    first_system, manifest = body["system"]
    assert first_system["cache_control"] == EPHEMERAL
    assert "cache_control" not in manifest
    last_block = body["messages"][-1]["content"][-1]
    assert last_block["type"] == "tool_result"
    assert last_block["cache_control"] == EPHEMERAL
    assert _count_cache_control(body) == 2
    assert "cache_control" not in body


async def test_switch_off_sends_the_same_body_without_markers(sent_bodies):
    marked = await _anthropic_body(sent_bodies, prompt_caching_enabled=True)
    unmarked = await _anthropic_body(sent_bodies, prompt_caching_enabled=False)

    assert _count_cache_control(unmarked) == 0
    assert unmarked == _without_cache_control(marked)


# Without the model check litellm would still mark both: OpenAI gpt-5.6+ with its own
# prompt_cache_breakpoint, Claude behind OpenRouter with cache_control.
@pytest.mark.parametrize(
    ("provider", "model"),
    [("openai", "gpt-5.6"), ("openrouter", "anthropic/claude-sonnet-5-5")],
    ids=["openai", "claude-via-openrouter"],
)
async def test_switch_on_for_a_model_without_anthropic_markers_sends_none(sent_bodies, provider, model):
    messages = copy.deepcopy(CONVERSATION)

    await _send(messages, _model_config(provider, model, prompt_caching_enabled=True))

    (body,) = sent_bodies
    wire = json.dumps(body)
    assert "cache_control" not in wire
    assert "prompt_cache" not in wire
    assert messages == CONVERSATION
