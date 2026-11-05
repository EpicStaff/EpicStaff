"""A failed LLM call reaches crew as a stop reason and an error kind, on every runner path.

Crew shows the user a text chosen by these two fields, never the raw error, so each path
a loop failure can take out of the agent service must keep them. Every path sends the
failure as ``agent.error``, never as an ``agent.result``: a crew that doesn't know a stop
reason yet would take that result for a success. A loop failure that isn't an LLM failure
arrives as ``internal_error`` without a kind. Real runners, loop and emitter; only the LLM
and Redis are replaced.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import litellm
import pytest

from app.emitters.redis_batch import RedisStreamBatchEmitter
from app.llm.client import LLMChunk, LLMClient
from app.loop.agent_loop import DefaultAgentLoop
from app.runners.deps import RunnerDependencies
from app.runners.list_of_tasks import ListOfTasksRunner
from app.runners.single_task import SingleTaskRunner
from shared.models.agent_service import AgentRequest, AgentSpec, RunType
from shared.models.ai_providers import LLMConfigData, LLMData
from tests.cancellation import never_cancelled
from tests.loop.test_default_agent_loop import FakeLLMClient
from tests.provider_errors import OPENAI_QUOTA_BODY, litellm_error_from_openai_response
from tests.runners.test_single_task_runner import FakeResolver, FakeResolverWithTools

pytestmark = pytest.mark.asyncio

RAW_PROVIDER_TEXT = "Incorrect API key provided: sk-proj-abc1****wxyz"
OUTPUT_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}}


class SlowLLMClient(LLMClient):
    """Never answers within the agent's time limit."""

    async def _never(self) -> AsyncIterator[LLMChunk]:
        await asyncio.sleep(5)
        yield LLMChunk(delta_text="too late")

    def chat(self, messages, tools, model_config, *, stream, runtime_config=None):
        return self._never()


FALLBACK_LLM = LLMData(provider="anthropic", config=LLMConfigData(model="claude-sonnet-4-5"))


def _agent(
    max_execution_time: float | None = None, fallback_llm: LLMData | None = None
) -> AgentSpec:
    return AgentSpec(
        id=12,
        name="Copywriter",
        instructions="Write copy.",
        llm=LLMData(provider="openai", config=LLMConfigData(model="gpt-4o")),
        fallback_llm=fallback_llm,
        max_iter=3,
        schema_max_retries=0,
        max_execution_time=max_execution_time,
    )


def _single_task(output_schema: dict | None = None, **agent_fields) -> AgentRequest:
    payload = {"task_instructions": "Write a slogan."}
    if output_schema is not None:
        payload["output_schema"] = output_schema
    return AgentRequest(
        correlation_id="run-1",
        run_type=RunType.SINGLE_TASK,
        agents=[_agent(**agent_fields)],
        payload=payload,
    )


def _list_of_tasks(**agent_fields) -> AgentRequest:
    return AgentRequest(
        correlation_id="run-1",
        run_type=RunType.LIST_OF_TASKS,
        agents=[_agent(**agent_fields)],
        payload={"tasks": [{"name": "slogan", "instructions": "Write a slogan."}]},
    )


def _authentication_error() -> Exception:
    return litellm.AuthenticationError(
        message=RAW_PROVIDER_TEXT, llm_provider="openai", model="gpt-4o"
    )


async def _terminal_envelope(runner_class, request, llm, resolver=None) -> tuple[str, dict]:
    published: list[dict] = []
    client = MagicMock()

    async def capture_publish(stream, fields, maxlen=None, approximate=True, ttl_s=None):
        published.append(fields)

    client.publish = capture_publish
    emitter = RedisStreamBatchEmitter(
        client=client,
        result_stream_prefix="agent.results",
        correlation_id=request.correlation_id,
        result_stream_ttl_s=60,
    )
    runner = runner_class(
        RunnerDependencies(resolver=resolver or FakeResolver(), loop=DefaultAgentLoop(llm))
    )

    await runner.execute(request, emitter, is_cancelled=never_cancelled)

    [fields] = published
    return fields["type"], json.loads(fields["payload"])


RUNNER_PATHS = pytest.mark.parametrize(
    ("runner_class", "request_", "resolver"),
    [
        (SingleTaskRunner, _single_task(), None),
        (SingleTaskRunner, _single_task(OUTPUT_SCHEMA), None),
        (SingleTaskRunner, _single_task(OUTPUT_SCHEMA), FakeResolverWithTools()),
        (ListOfTasksRunner, _list_of_tasks(), None),
    ],
    ids=["single-task", "schema-enforcer", "schema-tool-loop", "list-of-tasks"],
)


@RUNNER_PATHS
async def test_llm_failure_reaches_crew_with_its_kind(runner_class, request_, resolver):
    llm = FakeLLMClient([], chat_raises=_authentication_error())

    envelope_type, payload = await _terminal_envelope(runner_class, request_, llm, resolver)

    assert envelope_type == "agent.error"
    assert payload["stop_reason"] == "llm_error"
    assert payload["error_kind"] == "authentication"
    assert payload["failed_llm"] == "primary"


@pytest.mark.parametrize(
    ("runner_class", "request_"),
    [
        (SingleTaskRunner, _single_task(fallback_llm=FALLBACK_LLM)),
        (SingleTaskRunner, _single_task(OUTPUT_SCHEMA, fallback_llm=FALLBACK_LLM)),
        (ListOfTasksRunner, _list_of_tasks(fallback_llm=FALLBACK_LLM)),
    ],
    ids=["single-task", "schema-enforcer", "list-of-tasks"],
)
async def test_a_failed_fallback_reaches_crew_as_the_llm_that_failed(runner_class, request_):
    rate_limited = litellm.RateLimitError(message="slow down", llm_provider="openai", model="gpt-4o")
    llm = FakeLLMClient([rate_limited, _authentication_error()])

    envelope_type, payload = await _terminal_envelope(runner_class, request_, llm)

    assert envelope_type == "agent.error"
    assert payload["stop_reason"] == "llm_error"
    assert payload["error_kind"] == "authentication"
    assert payload["failed_llm"] == "fallback"


@RUNNER_PATHS
async def test_loop_failure_outside_the_llm_call_reaches_crew_without_a_kind(
    runner_class, request_, resolver
):
    llm = FakeLLMClient([], chat_raises=ConnectionError("Redis connection lost"))

    envelope_type, payload = await _terminal_envelope(runner_class, request_, llm, resolver)

    assert envelope_type == "agent.error"
    assert payload["stop_reason"] == "internal_error"
    assert payload["error_kind"] is None
    assert payload["failed_llm"] is None


@pytest.mark.parametrize(
    ("runner_class", "request_"),
    [
        (SingleTaskRunner, _single_task(max_execution_time=0.05)),
        (ListOfTasksRunner, _list_of_tasks(max_execution_time=0.05)),
    ],
    ids=["single-task", "list-of-tasks"],
)
async def test_agent_time_limit_reaches_crew_as_a_timeout(runner_class, request_):
    envelope_type, payload = await _terminal_envelope(runner_class, request_, SlowLLMClient())

    assert envelope_type == "agent.error"
    assert payload["stop_reason"] == "timeout"
    assert payload["error_kind"] is None


async def test_a_failed_single_task_without_a_schema_is_never_published_as_a_result():
    # Crew decides success on agent.result by its stop reason, so a crew older than
    # internal_error would accept this failure as the node's output.
    llm = FakeLLMClient([], chat_raises=await litellm_error_from_openai_response(429, OPENAI_QUOTA_BODY))

    envelope_type, payload = await _terminal_envelope(SingleTaskRunner, _single_task(), llm)

    assert envelope_type == "agent.error"
    assert payload["stop_reason"] == "llm_error"
    assert payload["error_kind"] == "quota_exceeded"


async def test_a_failure_outside_the_loop_carries_no_stop_reason_or_kind():
    request = AgentRequest(
        correlation_id="run-1", run_type=RunType.SINGLE_TASK, agents=[_agent()], payload={}
    )

    envelope_type, payload = await _terminal_envelope(
        SingleTaskRunner, request, FakeLLMClient([])
    )

    assert envelope_type == "agent.error"
    assert "stop_reason" not in payload
    assert "error_kind" not in payload
