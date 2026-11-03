import asyncio
import json

import pytest
from loguru import logger

from src.crew.services.graph import session_audit_provider
from src.crew.services.graph.session_audit_provider import (
    SessionAuditContext,
    clear_session_audit_context,
    emit_session_audit_event,
    register_session_audit_context,
)
from src.shared.audit.writers.session_writer import SessionAuditWriter
from tests.graph.recording_audit_client import RecordingAuditClient


class RecordingAuditWriter:
    def __init__(self):
        self.start_calls: list[dict] = []
        self.finish_calls: list[dict] = []

    async def add_start_message(self, **kwargs):
        self.start_calls.append(kwargs)

    async def add_finish_message(self, **kwargs):
        self.finish_calls.append(kwargs)


@pytest.fixture
def recording_writer(monkeypatch):
    writer = RecordingAuditWriter()
    monkeypatch.setattr(session_audit_provider, "AUDIT_TRAIL_ENABLED", True)
    monkeypatch.setattr(session_audit_provider, "get_session_audit_writer", lambda: writer)
    session_id = 501
    register_session_audit_context(
        session_id, SessionAuditContext(org_id=7, flow_name="flow", audit_retention_days=0)
    )
    yield writer, session_id
    clear_session_audit_context(session_id)


def _chunk(session_id: int, message_data: dict) -> str:
    return json.dumps({
        "session_id": session_id,
        "name": "node",
        "node_type": "python",
        "execution_order": 1,
        "uuid": "event-id",
        "message_data": message_data,
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("falsy_value", [False, 0, "", []])
async def test_falsy_node_input_and_output_reach_the_audit_writer_unchanged(
    recording_writer, falsy_value
):
    writer, session_id = recording_writer

    emit_session_audit_event(_chunk(session_id, {"message_type": "start", "input": falsy_value}))
    emit_session_audit_event(_chunk(session_id, {"message_type": "finish", "output": falsy_value}))
    await asyncio.sleep(0)

    assert writer.start_calls[0]["input_"] == falsy_value
    assert type(writer.start_calls[0]["input_"]) is type(falsy_value)
    assert writer.finish_calls[0]["output"] == falsy_value
    assert type(writer.finish_calls[0]["output"]) is type(falsy_value)


@pytest.mark.asyncio
async def test_missing_node_input_and_output_default_to_empty_dict(recording_writer):
    writer, session_id = recording_writer

    emit_session_audit_event(_chunk(session_id, {"message_type": "start"}))
    emit_session_audit_event(_chunk(session_id, {"message_type": "finish", "output": None}))
    await asyncio.sleep(0)

    assert writer.start_calls[0]["input_"] == {}
    assert writer.finish_calls[0]["output"] == {}


RETENTION_SESSION_ID = 7

# Each node message type, and how many events the writer emits for it: a start
# also writes the node's identity document.
MESSAGE_TYPES = [
    pytest.param({"message_type": "start", "input": {}}, 2, id="start"),
    pytest.param({"message_type": "finish", "output": {}}, 1, id="finish"),
    pytest.param({"message_type": "error", "details": "boom"}, 1, id="error"),
    pytest.param({"message_type": "python", "stdout": ""}, 1, id="custom"),
]


@pytest.fixture
def audit_client(monkeypatch):
    client = RecordingAuditClient()
    writer = SessionAuditWriter(client)
    monkeypatch.setattr(session_audit_provider, "AUDIT_TRAIL_ENABLED", True)
    monkeypatch.setattr(session_audit_provider, "get_session_audit_writer", lambda: writer)
    yield client
    clear_session_audit_context(RETENTION_SESSION_ID)


@pytest.fixture
def captured_logs():
    lines: list[str] = []
    sink_id = logger.add(lines.append, level="WARNING")
    yield lines
    logger.remove(sink_id)


def encoded_message(session_id: int, message_data: dict) -> str:
    return json.dumps({
        "session_id": session_id,
        "name": "node",
        "node_type": "python",
        "execution_order": 1,
        "uuid": f"event-{message_data['message_type']}",
        "message_data": message_data,
    })


async def _wait_for_events(client: RecordingAuditClient, count: int) -> None:
    async with asyncio.timeout(1):
        while len(client.events) < count:
            await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize(("message_data", "event_count"), MESSAGE_TYPES)
async def test_emitted_events_carry_retention_days(audit_client, message_data, event_count):
    register_session_audit_context(
        RETENTION_SESSION_ID,
        SessionAuditContext(org_id=1, flow_name="flow", audit_retention_days=30),
    )

    emit_session_audit_event(encoded_message(RETENTION_SESSION_ID, message_data))
    await _wait_for_events(audit_client, event_count)

    assert [event.retention_days for event in audit_client.events] == [30] * event_count


@pytest.mark.asyncio
async def test_event_of_a_session_without_audit_context_is_dropped_with_a_warning(
    audit_client, captured_logs
):
    emit_session_audit_event(
        encoded_message(RETENTION_SESSION_ID, {"message_type": "finish", "output": {}})
    )
    await asyncio.sleep(0)

    assert audit_client.events == []
    assert any(
        f"No audit context for session {RETENTION_SESSION_ID}" in line for line in captured_logs
    )
