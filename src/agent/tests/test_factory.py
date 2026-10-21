"""
Tests for RunnerFactory: pairing a RunType with its (Runner, Emitter).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.emitters.redis_tool_events import RedisStreamToolEventEmitter
from app.exceptions import UnknownRunTypeError
from app.factory import RunnerFactory
from app.runners.list_of_tasks import ListOfTasksRunner
from app.runners.single_task import SingleTaskRunner
from shared.models.agent_service import (
    AgentRequest,
    AgentSpec,
    RunType,
)
from shared.models.ai_providers import LLMConfigData, LLMData


def _agent_spec() -> AgentSpec:
    return AgentSpec(
        id=12,
        name="researcher",
        instructions="You research topics thoroughly.",
        llm=LLMData(provider="openai", config=LLMConfigData(model="gpt-4o")),
    )


def _request() -> AgentRequest:
    return AgentRequest(
        correlation_id="test-corr",
        run_type=RunType.SINGLE_TASK,
        agents=[_agent_spec()],
        payload={"task_instructions": "do it"},
    )


def _factory() -> RunnerFactory:
    factory = RunnerFactory(deps=MagicMock())
    factory.register(RunType.SINGLE_TASK, SingleTaskRunner)
    factory.register(RunType.LIST_OF_TASKS, ListOfTasksRunner)
    return factory


@pytest.mark.parametrize(
    ("run_type", "payload", "runner_class"),
    [
        (RunType.SINGLE_TASK, {"task_instructions": "do it"}, SingleTaskRunner),
        (RunType.LIST_OF_TASKS, {"tasks": [{"name": "t1", "instructions": "do it"}]}, ListOfTasksRunner),
    ],
)
def test_each_run_type_gets_its_runner_and_a_live_tool_event_emitter(run_type, payload, runner_class):
    request = AgentRequest(correlation_id="test-corr", run_type=run_type, agents=[_agent_spec()], payload=payload)

    runner, emitter = _factory().build(
        request, redis_client=MagicMock(), result_stream_prefix="agent.results", result_stream_ttl_s=3600
    )

    assert isinstance(runner, runner_class)
    assert isinstance(emitter, RedisStreamToolEventEmitter)


def test_unregistered_run_type_is_refused():
    with pytest.raises(UnknownRunTypeError):
        RunnerFactory(deps=MagicMock()).build(
            _request(), redis_client=MagicMock(), result_stream_prefix="agent.results", result_stream_ttl_s=3600
        )


async def test_built_emitter_publishes_to_stream_derived_from_request_correlation_id():
    factory = _factory()
    published: list[tuple[str, int | None]] = []
    client = MagicMock()

    async def capture_publish(
        stream: str,
        fields: dict,
        maxlen: int | None = 1_000_000,
        approximate: bool = True,
        ttl_s: int | None = None,
    ) -> None:
        published.append((stream, ttl_s))

    client.publish = capture_publish

    _runner, emitter = factory.build(
        _request(),
        redis_client=client,
        result_stream_prefix="agent.results",
        result_stream_ttl_s=3600,
    )
    await emitter.on_error(RuntimeError("boom"))

    assert published == [("agent.results:test-corr", 3600)]
