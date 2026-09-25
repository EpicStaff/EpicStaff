"""
Tests for RunnerFactory: pairing a RunType with its (Runner, Emitter).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.emitters.redis_batch import RedisStreamBatchEmitter
from app.emitters.redis_tool_events import RedisStreamToolEventEmitter
from app.enums import EmitterMode
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


def test_build_single_task_returns_runner_and_tool_event_emitter():
    factory = _factory()
    runner, emitter = factory.build(
        _request(),
        redis_client=MagicMock(),
        result_stream_prefix="agent.results",
        result_stream_ttl_s=3600,
    )

    assert isinstance(runner, SingleTaskRunner)
    assert isinstance(emitter, RedisStreamToolEventEmitter)


def test_build_list_of_tasks_returns_list_of_tasks_runner():
    factory = _factory()
    request = AgentRequest(
        correlation_id="test-corr",
        run_type=RunType.LIST_OF_TASKS,
        agents=[_agent_spec()],
        payload={"tasks": [{"name": "t1", "instructions": "do it"}]},
    )
    runner, emitter = factory.build(
        request,
        redis_client=MagicMock(),
        result_stream_prefix="agent.results",
        result_stream_ttl_s=3600,
    )

    assert isinstance(runner, ListOfTasksRunner)
    assert isinstance(emitter, RedisStreamToolEventEmitter)


def test_build_stream_mode_raises_not_implemented():
    factory = RunnerFactory(deps=MagicMock())

    with pytest.raises(NotImplementedError):
        factory._build_emitter(
            EmitterMode.STREAM,
            redis_client=MagicMock(),
            result_stream_prefix="agent.results",
            correlation_id="test-corr",
            result_stream_ttl_s=3600,
        )


def test_build_batch_mode_returns_batch_emitter():
    factory = RunnerFactory(deps=MagicMock())
    emitter = factory._build_emitter(
        EmitterMode.BATCH,
        redis_client=MagicMock(),
        result_stream_prefix="agent.results",
        correlation_id="test-corr",
        result_stream_ttl_s=3600,
    )

    assert isinstance(emitter, RedisStreamBatchEmitter)


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
