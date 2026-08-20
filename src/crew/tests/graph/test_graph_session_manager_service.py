"""Tests for EST-3285 4.2c: run-level token budget hard stop.

These tests exercise GraphSessionManagerService.run_session() directly,
stubbing out SessionGraphBuilder.compile_from_schema() so we can control
exactly which "custom" chunks stream through the loop -- without building a
real langgraph state machine. This keeps the tests focused on the budget
accounting / stop-triggering logic that lives in run_session() itself.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from dotdict import DotDict

from models.graph_models import FinishMessageData, GraphMessage
from services.graph.events import StopEvent
from services.graph.graph_session_manager_service import (
    GraphSessionManagerService,
    _extract_finish_token_total,
)
from services.graph.exceptions import StopSession
from src.shared.models import SessionData
from src.shared.models.graph_nodes import GraphData


def make_finish_chunk(
    session_id: int,
    total_tokens: int,
    execution_order: int = 0,
    name: str = "crew_node",
    subgraph_execution_ids: list[str] | None = None,
) -> tuple[str, GraphMessage]:
    """Build a ("custom", GraphMessage) chunk mimicking a CrewNode finish
    message with token usage attached to output (see crew_node.py:92-111 and
    custom_message_writer.py add_finish_message)."""
    message_data = FinishMessageData(
        output={
            "message": "ok",
            "token_usage": {
                "total_tokens": total_tokens,
                "prompt_tokens": total_tokens,
                "completion_tokens": 0,
                "successful_requests": 1,
            },
        },
        state={"variables": {}, "state_history": []},
    )
    graph_message = GraphMessage(
        session_id=session_id,
        name=name,
        execution_order=execution_order,
        message_data=message_data,
    )
    if subgraph_execution_ids is not None:
        # Mirrors subgraph_node.py::_execute_subgraph tagging nested
        # messages with the ids of the subgraph(s) they streamed through.
        graph_message.message_data.subgraph_execution_ids = subgraph_execution_ids
    return ("custom", graph_message)


class FakeCompiledGraph:
    """Stands in for the real langgraph CompiledStateGraph returned by
    SessionGraphBuilder.compile_from_schema()."""

    def __init__(self, chunks, final_state=None):
        self._chunks = chunks
        self._final_state = final_state or {
            "variables": DotDict({}),
            "state_history": [],
        }

    async def astream(self, input, config, stream_mode):
        for item in self._chunks:
            yield item
        yield ("values", self._final_state)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """GraphSessionManagerService is a process-wide singleton
    (utils/singleton_meta.py). Reset it around every test so instantiating
    it with test-only mocks doesn't leak into/from other test modules."""
    from utils.singleton_meta import SingletonMeta

    SingletonMeta._instances.pop(GraphSessionManagerService, None)
    yield
    SingletonMeta._instances.pop(GraphSessionManagerService, None)


@pytest.fixture
def service():
    redis_service = Mock()
    redis_service.aupdate_session_status = AsyncMock()
    redis_service.publish = Mock()

    svc = GraphSessionManagerService(
        redis_service=redis_service,
        python_code_executor_service=Mock(),
        session_schema_channel="session_schema",
        session_timeout_channel="session_timeout",
        crewai_output_channel="crewai_output",
        stop_session_channel="stop_session",
        knowledge_search_service=Mock(),
    )
    return svc


def _session_data(session_id: int, token_budget: int | None = None) -> SessionData:
    initial_state = {}
    if token_budget is not None:
        initial_state["__token_budget__"] = token_budget
    return SessionData(
        id=session_id,
        graph=GraphData(name="g", entrypoint="__end__", end_node=None),
        initial_state=initial_state,
    )


def _patch_builder(monkeypatch, compiled_graph, end_node_result=None):
    class FakeSessionGraphBuilder:
        def __init__(self, *args, **kwargs):
            self.end_node_result = end_node_result or {}

        def compile_from_schema(self, session_data):
            return compiled_graph

    monkeypatch.setattr(
        "services.graph.graph_session_manager_service.SessionGraphBuilder",
        FakeSessionGraphBuilder,
    )


def test_extract_finish_token_total_reads_output_token_usage():
    message_data = {
        "message_type": "finish",
        "output": {"token_usage": {"total_tokens": 42}},
    }
    assert _extract_finish_token_total(message_data) == 42


def test_extract_finish_token_total_ignores_messages_without_tokens():
    assert _extract_finish_token_total({"message_type": "start"}) == 0
    assert _extract_finish_token_total({}) == 0
    assert _extract_finish_token_total(None) == 0  # type: ignore[arg-type]
