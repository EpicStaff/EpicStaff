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
        crew_parser_service=Mock(),
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


@pytest.mark.asyncio
async def test_budget_exceeded_stops_session(service, monkeypatch):
    session_id = 1
    chunks = [
        make_finish_chunk(session_id, total_tokens=100),
        make_finish_chunk(session_id, total_tokens=100),
    ]
    _patch_builder(monkeypatch, FakeCompiledGraph(chunks))

    stop_event = StopEvent()
    session_data = _session_data(session_id, token_budget=150)

    await service.run_session(session_data, stop_event)

    assert stop_event.is_set()
    assert stop_event.reason == "token budget exceeded"

    status_calls = service.redis_service.aupdate_session_status.call_args_list
    stop_calls = [c for c in status_calls if c.kwargs.get("status") == "stop"]
    assert stop_calls, f"expected a status='stop' update, got: {status_calls}"
    assert stop_calls[-1].kwargs.get("reason") == "token budget exceeded"


@pytest.mark.asyncio
async def test_no_budget_configured_is_inert(service, monkeypatch):
    session_id = 2
    chunks = [
        make_finish_chunk(session_id, total_tokens=10_000_000),
    ]
    _patch_builder(monkeypatch, FakeCompiledGraph(chunks))

    stop_event = StopEvent()
    session_data = _session_data(session_id, token_budget=None)

    await service.run_session(session_data, stop_event)

    assert not stop_event.is_set()
    status_calls = service.redis_service.aupdate_session_status.call_args_list
    statuses = [c.kwargs.get("status") for c in status_calls]
    assert "end" in statuses
    assert "stop" not in statuses


@pytest.mark.asyncio
async def test_budget_is_per_session_not_shared(service, monkeypatch):
    """Two sessions each with a 100-token budget: session A stays under
    budget, session B goes over. Session A must not be affected by
    anything B does (regression item #1: no cross-session leakage of the
    running total, since it's a local variable in run_session())."""
    session_a_id, session_b_id = 10, 20

    chunks_a = [make_finish_chunk(session_a_id, total_tokens=60)]
    _patch_builder(monkeypatch, FakeCompiledGraph(chunks_a))
    stop_event_a = StopEvent()
    await service.run_session(
        _session_data(session_a_id, token_budget=100), stop_event_a
    )
    assert not stop_event_a.is_set()

    chunks_b = [
        make_finish_chunk(session_b_id, total_tokens=60),
        make_finish_chunk(session_b_id, total_tokens=60),
    ]
    _patch_builder(monkeypatch, FakeCompiledGraph(chunks_b))
    stop_event_b = StopEvent()
    await service.run_session(
        _session_data(session_b_id, token_budget=100), stop_event_b
    )
    assert stop_event_b.is_set()

    # Re-running session A's exact scenario again afterwards must still not
    # trip -- proves B's overage never bled into a shared counter.
    chunks_a_again = [make_finish_chunk(session_a_id, total_tokens=60)]
    _patch_builder(monkeypatch, FakeCompiledGraph(chunks_a_again))
    stop_event_a2 = StopEvent()
    await service.run_session(
        _session_data(session_a_id, token_budget=100), stop_event_a2
    )
    assert not stop_event_a2.is_set()


@pytest.mark.asyncio
async def test_subgraph_finish_messages_count_toward_budget(service, monkeypatch):
    """Subgraph finish messages are re-streamed through the parent's writer
    (subgraphs/subgraph_node.py::_execute_subgraph) and tagged with
    subgraph_execution_ids, but land in run_session()'s custom-stream loop
    just like top-level crew node messages. They must count toward the
    same running total."""
    session_id = 30
    chunks = [
        # A nested subgraph's own CrewNode finish message, as it would
        # appear after being re-streamed by SubGraphNode._execute_subgraph.
        make_finish_chunk(
            session_id,
            total_tokens=90,
            name="nested_crew_node",
            subgraph_execution_ids=["exec-1"],
        ),
        make_finish_chunk(session_id, total_tokens=90, name="top_level_crew_node"),
    ]
    _patch_builder(monkeypatch, FakeCompiledGraph(chunks))

    stop_event = StopEvent()
    session_data = _session_data(session_id, token_budget=150)

    await service.run_session(session_data, stop_event)

    assert stop_event.is_set(), (
        "subgraph token usage (90) + top-level token usage (90) = 180 "
        "must exceed the 150 budget"
    )
    assert stop_event.reason == "token budget exceeded"
