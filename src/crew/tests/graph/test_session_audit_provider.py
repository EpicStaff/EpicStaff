import asyncio

import pytest

from src.crew.services.graph import session_audit_provider
from src.crew.services.graph.session_audit_provider import (
    clear_session_flow_name,
    clear_session_org,
    emit_session_audit_event,
    register_session_flow_name,
    register_session_org,
)


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
    monkeypatch.setattr(session_audit_provider, "get_session_audit_writer", lambda: writer)
    session_id = 501
    register_session_org(session_id, org_id=7)
    register_session_flow_name(session_id, "flow")
    yield writer, session_id
    clear_session_org(session_id)
    clear_session_flow_name(session_id)


def _chunk(session_id: int, message_data: dict) -> dict:
    return {
        "session_id": session_id,
        "name": "node",
        "node_type": "python",
        "execution_order": 1,
        "uuid": "event-id",
        "message_data": message_data,
    }


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
