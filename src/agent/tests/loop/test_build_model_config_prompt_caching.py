"""
Prompt-cache injection points on every LLM call the agent loop makes.

The loop runs for real against ``FakeLLMClient``; the assertions read the model
config each call hands to the LLM client. ``tests/llm/test_prompt_cache_wire.py``
shows what litellm sends for these points.
"""

from __future__ import annotations

import litellm
import pytest
from app.loop.agent_loop import DefaultAgentLoop
from app.loop.context import AgentContext
from app.loop.stop_policy import MaxIterAndNoToolCalls
from app.output.enforcer import StructuredOutputEnforcer
from app.tools.system_tools.structured_output import ANSWER_TOOL
from shared.models.agent_service import AgentSpec
from shared.models.ai_providers import LLMConfigData, LLMData
from tests.cancellation import never_cancelled
from tests.loop.test_default_agent_loop import (
    FakeLLMClient,
    RecordingEmitter,
    StubToolRegistry,
    _provider_error,
    text_chunks,
    tool_chunks,
)
from tests.secret_sealing import agent_cryptographer

POINTS_KEY = "cache_control_injection_points"
SYSTEM_PROMPT_AND_LAST_MESSAGE = [
    {"location": "message", "index": 0},
    {"location": "message", "index": -1},
]

CLAUDE = LLMData(provider="anthropic", config=LLMConfigData(model="claude-sonnet-5-5"))
GPT = LLMData(provider="openai", config=LLMConfigData(model="gpt-5.6"))


def _context(
    llm: LLMData,
    *,
    prompt_caching_enabled: bool = True,
    fallback_llm: LLMData | None = None,
    tool_choice=None,
    max_consecutive_failures: int | None = None,
) -> AgentContext:
    agent = AgentSpec(
        id=1,
        name="test-agent",
        instructions="You are a test assistant.",
        llm=llm,
        fallback_llm=fallback_llm,
        max_consecutive_failures=max_consecutive_failures,
        prompt_caching_enabled=prompt_caching_enabled,
    )
    return AgentContext(
        agent=agent,
        attachments=[],
        correlation_id="test-corr",
        tool_choice=tool_choice,
        is_cancelled=never_cancelled,
    )


async def _received_configs(llm_client: FakeLLMClient, context: AgentContext, tools=None) -> list[dict]:
    await DefaultAgentLoop(llm_client, agent_cryptographer()).run(
        context, StubToolRegistry(tools or {}), RecordingEmitter(), MaxIterAndNoToolCalls(max_iter=5)
    )
    return llm_client.received_configs


@pytest.mark.parametrize(
    ("llm", "prompt_caching_enabled", "expected_points"),
    [
        (CLAUDE, True, SYSTEM_PROMPT_AND_LAST_MESSAGE),
        (
            LLMData(provider="bedrock", config=LLMConfigData(model="us.anthropic.claude-sonnet-5-5")),
            True,
            SYSTEM_PROMPT_AND_LAST_MESSAGE,
        ),
        (CLAUDE, False, None),
        (GPT, True, None),
        (LLMData(provider="openrouter", config=LLMConfigData(model="anthropic/claude-sonnet-5-5")), True, None),
    ],
    ids=["claude-on", "bedrock-claude-on", "claude-off", "openai-on", "claude-via-openrouter-on"],
)
async def test_points_are_sent_only_when_switched_on_for_a_model_taking_anthropic_markers(
    llm, prompt_caching_enabled, expected_points
):
    (config,) = await _received_configs(
        FakeLLMClient([text_chunks("ok")]), _context(llm, prompt_caching_enabled=prompt_caching_enabled)
    )

    assert config.get(POINTS_KEY) == expected_points


async def test_switch_changes_nothing_else_in_the_config():
    # A model that refuses sampling and forced tool choice, so both rewrites are exercised.
    llm = LLMData(
        provider="bedrock",
        config=LLMConfigData(
            model="us.anthropic.claude-sonnet-5-5",
            parameters={"temperature": 0.5, "top_p": 0.9, "reasoning_effort": "high"},
        ),
    )
    forced = {"type": "function", "function": {"name": "submit_final_answer"}}

    (switched_on,) = await _received_configs(
        FakeLLMClient([text_chunks("ok")]), _context(llm, tool_choice=forced)
    )
    (switched_off,) = await _received_configs(
        FakeLLMClient([text_chunks("ok")]), _context(llm, prompt_caching_enabled=False, tool_choice=forced)
    )

    assert switched_on.pop(POINTS_KEY) == SYSTEM_PROMPT_AND_LAST_MESSAGE
    assert switched_on == switched_off
    assert switched_off["tool_choice"] == "auto"
    assert "temperature" not in switched_off


@pytest.mark.parametrize(
    ("primary", "fallback", "expected_points"),
    [
        (CLAUDE, GPT, [SYSTEM_PROMPT_AND_LAST_MESSAGE, None]),
        (GPT, CLAUDE, [None, SYSTEM_PROMPT_AND_LAST_MESSAGE]),
    ],
    ids=["claude-to-gpt", "gpt-to-claude"],
)
async def test_fallback_call_follows_the_fallback_model(primary, fallback, expected_points):
    llm_client = FakeLLMClient([_provider_error(litellm.RateLimitError), text_chunks("ok")])

    configs = await _received_configs(llm_client, _context(primary, fallback_llm=fallback))

    assert [config.get(POINTS_KEY) for config in configs] == expected_points


async def test_final_call_without_tools_carries_the_points():
    llm_client = FakeLLMClient([tool_chunks("c1", "bad", "{}"), text_chunks("summary")])

    def bad_tool(args):
        raise RuntimeError("boom")

    configs = await _received_configs(
        llm_client, _context(CLAUDE, max_consecutive_failures=1), tools={"bad": bad_tool}
    )

    assert llm_client.received_tools[-1] == []
    assert [config.get(POINTS_KEY) for config in configs] == [SYSTEM_PROMPT_AND_LAST_MESSAGE] * 2


async def test_structured_output_call_carries_the_points():
    llm_client = FakeLLMClient([tool_chunks("c1", ANSWER_TOOL, '{"answer": "yes"}')])
    enforcer = StructuredOutputEnforcer(DefaultAgentLoop(llm_client, agent_cryptographer()), max_retries=0)
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}

    result = await enforcer.enforce(_context(CLAUDE), schema, RecordingEmitter())

    assert result.parsed == {"answer": "yes"}
    (config,) = llm_client.received_configs
    assert config[POINTS_KEY] == SYSTEM_PROMPT_AND_LAST_MESSAGE
