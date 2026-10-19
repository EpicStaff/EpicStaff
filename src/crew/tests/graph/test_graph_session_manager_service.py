"""run-level token budget hard stop.

These tests exercise GraphSessionManagerService.run_session() directly,
stubbing out SessionGraphBuilder.compile_from_schema() so we can control
exactly which "custom" chunks stream through the loop -- without building a
real langgraph state machine. This keeps the tests focused on the budget
accounting / stop-triggering logic that lives in run_session() itself.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from datetime import datetime
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import redis
from dotdict import DotDict
from fakeredis import FakeAsyncRedis
from loguru import logger

from models.graph_models import FinishMessageData, GraphMessage
from services.graph.events import StopEvent
from services.graph.exceptions import StopSession
from services.graph.graph_session_manager_service import GraphSessionManagerService
from services.redis_service import RedisService
from src.crew.services.graph import session_audit_provider
from src.crew.services.graph.session_audit_provider import emit_session_audit_event
from src.shared.audit.writers.session_writer import SessionAuditWriter
from src.shared.models import SessionData
from src.shared.models.graph_nodes import GraphData
from tests.graph.rebuild_counting_dict import RebuildCountingDict
from tests.graph.recording_audit_client import RecordingAuditClient


def make_finish_chunk(
    session_id: int,
    total_tokens: int,
    execution_order: int = 0,
    name: str = "agent_node",
    subgraph_execution_ids: list[str] | None = None,
) -> tuple[str, GraphMessage]:
    """Build a ("custom", GraphMessage) chunk mimicking an AgentNode/TaskNode
    finish message with token usage attached to output (see agent_node.py
    and custom_message_writer.py add_finish_message)."""
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
    redis_service.aset_session_final_variables = AsyncMock()
    redis_service.aadd_graph_message = AsyncMock()

    svc = GraphSessionManagerService(
        redis_service=redis_service,
        python_code_executor_service=Mock(),
        session_schema_channel="session_schema",
        session_timeout_channel="session_timeout",
        stop_session_channel="stop_session",
        knowledge_search_service=Mock(),
    )
    return svc


def _session_data(
    session_id: int, token_budget: int | None = None, audit_retention_days: int = 0
) -> SessionData:
    initial_state = {}
    if token_budget is not None:
        initial_state["__token_budget__"] = token_budget
    return SessionData(
        id=session_id,
        org_id=1,
        graph=GraphData(name="g", entrypoint="__end__", end_node=None),
        initial_state=initial_state,
        audit_retention_days=audit_retention_days,
    )


def _patch_builder(monkeypatch, compiled_graph, end_node_result=None):
    class FakeRememberedOutputsStore:
        async def clear(self, session_id):
            return None

    class FakeSessionGraphBuilder:
        def __init__(self, *args, **kwargs):
            self.end_node_result = end_node_result or {}
            self.remembered_outputs_store = FakeRememberedOutputsStore()

        def compile_from_schema(self, session_data):
            return compiled_graph

    monkeypatch.setattr(
        "services.graph.graph_session_manager_service.SessionGraphBuilder",
        FakeSessionGraphBuilder,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("finish_tokens", "budget", "expected_statuses"),
    [
        pytest.param([100, 100], 150, ["run", "stop"], id="over-budget-stops"),
        pytest.param([60], 100, ["run", "end"], id="under-budget-ends"),
        pytest.param([10_000_000], None, ["run", "end"], id="no-budget-never-stops"),
        # A subgraph's finish messages are re-streamed through the parent and count too.
        pytest.param([("nested", 90), 90], 150, ["run", "stop"], id="subgraph-tokens-count"),
    ],
)
async def test_token_budget(service, monkeypatch, finish_tokens, budget, expected_statuses):
    session_id = 1
    chunks = [
        make_finish_chunk(session_id, total_tokens=tokens[1], subgraph_execution_ids=["exec-1"])
        if isinstance(tokens, tuple)
        else make_finish_chunk(session_id, total_tokens=tokens)
        for tokens in finish_tokens
    ]
    _patch_builder(monkeypatch, FakeCompiledGraph(chunks))
    stop_event = StopEvent()

    await service.run_session(_session_data(session_id, token_budget=budget), stop_event)

    status_calls = service.redis_service.aupdate_session_status.call_args_list
    assert [call.kwargs["status"] for call in status_calls] == expected_statuses
    stopped = expected_statuses[-1] == "stop"
    assert stop_event.is_set() is stopped
    if stopped:
        assert stop_event.reason == status_calls[-1].kwargs["reason"] == "token budget exceeded"
        # A stopped session has no final variables to hand over.
        service.redis_service.aset_session_final_variables.assert_not_called()


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
async def test_handle_stop_session_skips_status_publish_when_not_in_pool(service):
    session_id = 999
    data = json.dumps({"session_id": session_id})

    await service._handle_stop_session(data)

    service.redis_service.aupdate_session_status.assert_not_called()
    assert session_id not in service.session_graph_pool


@pytest.mark.asyncio
async def test_handle_stop_session_publishes_status_when_in_pool(service):
    session_id = 998
    running_session = SimpleNamespace(stop_event=StopEvent())
    service.session_graph_pool[session_id] = running_session

    data = json.dumps({"session_id": session_id})
    await service._handle_stop_session(data)

    service.redis_service.aupdate_session_status.assert_called_once_with(
        session_id=session_id, status="stop"
    )
    assert running_session.stop_event.is_set()
    assert session_id not in service.session_graph_pool


@pytest.mark.asyncio
async def test_streamed_messages_and_graph_end_go_to_the_stream_before_end_status(
    service, monkeypatch
):
    session_id = 31
    _patch_builder(
        monkeypatch, FakeCompiledGraph([make_finish_chunk(session_id, total_tokens=5)])
    )

    await service.run_session(_session_data(session_id), StopEvent())

    calls = [
        (name, call_args, call_kwargs)
        for name, call_args, call_kwargs in service.redis_service.mock_calls
        if name in ("aadd_graph_message", "aupdate_session_status")
    ]
    added_messages = [
        json.loads(call_args[1]) for name, call_args, _ in calls if name == "aadd_graph_message"
    ]
    assert [message["message_data"]["message_type"] for message in added_messages] == [
        "finish",
        "graph_end",
    ]
    assert all(message["session_id"] == session_id for message in added_messages)
    assert len({message["uuid"] for message in added_messages}) == 2
    assert [name for name, _, call_kwargs in calls if call_kwargs.get("status") != "run"] == [
        "aadd_graph_message",
        "aadd_graph_message",
        "aupdate_session_status",
    ]


def _redis_calls(service, *names):
    return [
        (name, call_kwargs)
        for name, _, call_kwargs in service.redis_service.mock_calls
        if name in names
    ]


@pytest.mark.asyncio
async def test_end_writes_final_variables_before_publishing_end_status(
    service, monkeypatch
):
    session_id = 40
    final_state = {
        "variables": DotDict({"final_result": "done", "counter": 3}),
        "state_history": [],
    }
    _patch_builder(monkeypatch, FakeCompiledGraph([], final_state=final_state))

    await service.run_session(_session_data(session_id), StopEvent())

    assert _redis_calls(
        service, "aupdate_session_status", "aset_session_final_variables"
    ) == [
        ("aupdate_session_status", {"session_id": session_id, "status": "run"}),
        (
            "aset_session_final_variables",
            {
                "session_id": session_id,
                "variables": {"final_result": "done", "counter": 3},
            },
        ),
        ("aupdate_session_status", {"session_id": session_id, "status": "end"}),
    ]


@pytest.mark.asyncio
async def test_end_is_published_when_final_variables_write_fails(service, monkeypatch):
    session_id = 41
    _patch_builder(monkeypatch, FakeCompiledGraph([]))
    service.redis_service.aset_session_final_variables.side_effect = (
        redis.ConnectionError("redis down")
    )

    await service.run_session(_session_data(session_id), StopEvent())

    statuses = [
        call.kwargs["status"]
        for call in service.redis_service.aupdate_session_status.call_args_list
    ]
    assert statuses == ["run", "end"]


@pytest.mark.asyncio
async def test_unserialisable_final_variables_end_the_session_as_error(
    service, monkeypatch
):
    session_id = 44
    final_state = {
        "variables": DotDict({"finished_at": datetime(2026, 1, 1)}),
        "state_history": [],
    }
    _patch_builder(monkeypatch, FakeCompiledGraph([], final_state=final_state))

    # The real write, onto fake Redis (RedisService is a singleton, so bind it by hand).
    service.redis_service.aset_session_final_variables.side_effect = partial(
        RedisService.aset_session_final_variables,
        SimpleNamespace(aioredis_client=FakeAsyncRedis()),
    )

    await service.run_session(_session_data(session_id), StopEvent())

    status_calls = service.redis_service.aupdate_session_status.call_args_list
    assert [call.kwargs["status"] for call in status_calls] == ["run", "error"]
    assert "not JSON serializable" in status_calls[-1].kwargs["error"]


@pytest.mark.asyncio
async def test_failed_session_does_not_write_final_variables(service, monkeypatch):
    session_id = 43

    class FailingGraph:
        async def astream(self, input, config, stream_mode):
            raise RuntimeError("node crashed")
            yield

    _patch_builder(monkeypatch, FailingGraph())

    await service.run_session(_session_data(session_id), StopEvent())

    service.redis_service.aset_session_final_variables.assert_not_called()
    statuses = [
        call.kwargs["status"]
        for call in service.redis_service.aupdate_session_status.call_args_list
    ]
    assert statuses == ["run", "error"]


class _ReprCountingStr(str):
    """A state value that counts how often it is rendered into a log line."""

    render_count = 0

    def __repr__(self):
        type(self).render_count += 1
        return super().__repr__()


@pytest.fixture
def production_log_level():
    """Configure the crew stdout sink at INFO, the production level, for one test.

    The suite may run with any CREW_LOG_LEVEL (CI uses the dev default, DEBUG), so the
    level is pinned here and the suite's own sink is restored afterwards.
    """
    import settings
    import utils.logger

    suite_log_level = settings.LOG_LEVEL
    settings.LOG_LEVEL = "INFO"
    importlib.reload(utils.logger)
    yield
    settings.LOG_LEVEL = suite_log_level
    importlib.reload(utils.logger)


@pytest.mark.asyncio
async def test_streamed_state_is_not_rendered_for_debug_logs_at_info_level(
    service, monkeypatch, production_log_level
):
    _ReprCountingStr.render_count = 0
    final_state = {
        "variables": DotDict({}),
        "state_history": [_ReprCountingStr("large node output")],
    }
    _patch_builder(monkeypatch, FakeCompiledGraph([], final_state=final_state))

    await service.run_session(_session_data(45), StopEvent())

    statuses = [
        call.kwargs["status"]
        for call in service.redis_service.aupdate_session_status.call_args_list
    ]
    assert statuses == ["run", "end"]
    assert _ReprCountingStr.render_count == 0


@pytest.mark.asyncio
async def test_audit_writer_failure_does_not_fail_the_session(service, monkeypatch):
    def broken_audit_writer():
        raise RuntimeError("audit client misconfigured")

    monkeypatch.setattr(
        "services.graph.graph_session_manager_service.get_session_audit_writer",
        broken_audit_writer,
    )
    _patch_builder(monkeypatch, FakeCompiledGraph([]))

    await service.run_session(_session_data(46), StopEvent())

    statuses = [
        call.kwargs.get("status")
        for call in service.redis_service.aupdate_session_status.call_args_list
    ]
    assert "end" in statuses
    assert "error" not in statuses



@pytest.mark.asyncio
async def test_streamed_message_state_is_sent_without_being_rebuilt(service, monkeypatch):
    session_id = 32
    variables = RebuildCountingDict(customer=RebuildCountingDict(name="Ada"))
    finish_chunk = (
        "custom",
        GraphMessage(
            session_id=session_id,
            name="python_node",
            execution_order=0,
            message_data=FinishMessageData(output={}, state={"variables": variables}),
        ),
    )
    _patch_builder(monkeypatch, FakeCompiledGraph([finish_chunk]))
    RebuildCountingDict.constructions = 0

    await service.run_session(_session_data(session_id), StopEvent())

    assert RebuildCountingDict.constructions == 0
    first_added = service.redis_service.aadd_graph_message.await_args_list[0]
    assert json.loads(first_added.args[1])["message_data"]["state"]["variables"] == {
        "customer": {"name": "Ada"}
    }


@pytest.mark.asyncio
async def test_session_stopped_while_queued_does_not_run(service, monkeypatch):
    _patch_builder(monkeypatch, FakeCompiledGraph([]))

    stop_event = StopEvent(default_status="expired")
    stop_event.set()

    await service.session_runner(_session_data(session_id=3), stop_event)

    service.redis_service.aupdate_session_status.assert_not_called()


@pytest.mark.asyncio
async def test_session_stopped_while_queued_is_audited_as_skipped(service, monkeypatch):
    audit_calls: list[tuple[str, dict]] = []

    class RecordingAuditWriter:
        async def add_session_start(self, **kwargs):
            audit_calls.append(("start", kwargs))

        async def add_session_end(self, **kwargs):
            audit_calls.append(("end", kwargs))

    monkeypatch.setattr(
        "services.graph.graph_session_manager_service.get_session_audit_writer",
        RecordingAuditWriter,
    )
    _patch_builder(monkeypatch, FakeCompiledGraph([]))
    stop_event = StopEvent(default_status="expired")
    stop_event.set()

    await service.session_runner(_session_data(session_id=4), stop_event)
    async with asyncio.timeout(1):
        while len(audit_calls) < 2:
            await asyncio.sleep(0)

    assert [kind for kind, _ in audit_calls] == ["start", "end"]
    end_call = audit_calls[1][1]
    assert end_call["session_id"] == 4
    assert end_call["name"] == "Session Skipped"
    assert end_call["details"] == {
        "reason": "stopped while queued",
        "session_status": "expired",
    }


@pytest.fixture
def audit_client(monkeypatch):
    client = RecordingAuditClient()
    writer = SessionAuditWriter(client)
    monkeypatch.setattr(session_audit_provider, "AUDIT_TRAIL_ENABLED", True)
    monkeypatch.setattr(session_audit_provider, "get_session_audit_writer", lambda: writer)
    monkeypatch.setattr(
        "services.graph.graph_session_manager_service.get_session_audit_writer", lambda: writer
    )
    return client


@pytest.fixture
def captured_logs():
    lines: list[str] = []
    sink_id = logger.add(lines.append, level="WARNING")
    yield lines
    logger.remove(sink_id)


async def _wait_for_audit_events(client, count: int) -> None:
    async with asyncio.timeout(1):
        while len(client.events) < count:
            await asyncio.sleep(0)


class RaisingCompiledGraph:
    def __init__(self, error: BaseException):
        self._error = error

    async def astream(self, input, config, stream_mode):
        raise self._error
        yield


AUDITED_SESSION_ID = 61

# Every way a session can end. The event count is the session start (identity
# document + event), any node events, and the session end.
TERMINAL_PATHS = [
    pytest.param(
        lambda: FakeCompiledGraph([make_finish_chunk(AUDITED_SESSION_ID, 10)]),
        False,
        "Session End",
        4,
        id="completed",
    ),
    pytest.param(
        lambda: RaisingCompiledGraph(RuntimeError("node crashed")),
        False,
        "Session Failed",
        3,
        id="failed",
    ),
    pytest.param(
        lambda: RaisingCompiledGraph(asyncio.CancelledError()),
        False,
        "Session Cancelled",
        3,
        id="cancelled",
    ),
    pytest.param(
        lambda: RaisingCompiledGraph(StopSession(status="stop")),
        False,
        "Session Stopped",
        3,
        id="stopped",
    ),
    pytest.param(
        lambda: FakeCompiledGraph([]),
        True,
        "Session Skipped",
        3,
        id="skipped-in-queue",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("build_graph", "stopped_while_queued", "end_event_name", "event_count"), TERMINAL_PATHS
)
async def test_every_audit_event_carries_the_sessions_retention_and_none_follow_the_end(
    service,
    monkeypatch,
    audit_client,
    captured_logs,
    build_graph,
    stopped_while_queued,
    end_event_name,
    event_count,
):
    _patch_builder(monkeypatch, build_graph())
    stop_event = StopEvent()
    if stopped_while_queued:
        stop_event.set()

    await service.session_runner(
        _session_data(AUDITED_SESSION_ID, audit_retention_days=90), stop_event
    )
    await _wait_for_audit_events(audit_client, event_count)

    assert audit_client.events[-1].name == end_event_name
    assert [event.retention_days for event in audit_client.events] == [90] * event_count

    logs_before_late_message = len(captured_logs)
    _, late_message = make_finish_chunk(AUDITED_SESSION_ID, 1)
    emit_session_audit_event(GraphMessage.encode_payload(late_message.to_payload()))
    await asyncio.sleep(0)

    assert len(audit_client.events) == event_count
    assert any(
        f"No audit context for session {AUDITED_SESSION_ID}" in line
        for line in captured_logs[logs_before_late_message:]
    )
