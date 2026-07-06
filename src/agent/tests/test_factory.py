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
    return factory


def test_build_single_task_returns_runner_and_tool_event_emitter():
    factory = _factory()
    runner, emitter = factory.build(
        _request(), redis_client=MagicMock(), result_stream="agent.results"
    )

    assert isinstance(runner, SingleTaskRunner)
    assert isinstance(emitter, RedisStreamToolEventEmitter)


def test_build_stream_mode_raises_not_implemented():
    factory = RunnerFactory(deps=MagicMock())

    with pytest.raises(NotImplementedError):
        factory._build_emitter(
            EmitterMode.STREAM,
            redis_client=MagicMock(),
            result_stream="agent.results",
            correlation_id="test-corr",
        )


def test_build_batch_mode_returns_batch_emitter():
    factory = RunnerFactory(deps=MagicMock())
    emitter = factory._build_emitter(
        EmitterMode.BATCH,
        redis_client=MagicMock(),
        result_stream="agent.results",
        correlation_id="test-corr",
    )

    assert isinstance(emitter, RedisStreamBatchEmitter)
