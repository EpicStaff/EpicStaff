"""AgentStreamEventForwarder: turns agent-service envelopes into session stream messages."""

import pytest

from services.graph.nodes.agent_stream_events import AgentStreamEventForwarder
from src.shared.redis_streams import StreamEnvelope


class RecordingMessageWriter:
    def __init__(self):
        self.messages: list[dict] = []

    def add_custom_message(self, session_id, node_name, writer, execution_order, message_data):
        self.messages.append(message_data)


@pytest.fixture
def message_writer():
    return RecordingMessageWriter()


@pytest.fixture
def forwarder(message_writer):
    return AgentStreamEventForwarder(
        custom_session_message_writer=message_writer,
        session_id=1,
        node_name="agent_node_1",
        writer=lambda message: None,
        execution_order=1,
        stream_message_type="agent_node_stream",
        agent_id=7,
    )


def test_fallback_envelope_becomes_an_llm_fallback_event_with_the_payload_unchanged(
    forwarder, message_writer
):
    payload = {
        "task": {"name": "task_a", "order": 0},
        "primary": {"config_name": "main", "model": "gpt-4o"},
        "fallback": {"config_name": None, "model": "claude-sonnet"},
        "error_type": "RateLimitError",
    }

    forwarder(StreamEnvelope(type="agent.llm_fallback", correlation_id="corr-1", payload=payload))

    assert message_writer.messages == [
        {
            "message_type": "agent_node_stream",
            "event": "llm_fallback",
            "step_id": 1,
            "is_final": False,
            "agent_id": 7,
            "data": payload,
        }
    ]


def test_fallback_skipped_notice_is_one_message_that_takes_a_step_number(forwarder, message_writer):
    forwarder.forward_fallback_skipped("Fallback LLM was skipped: no API key.")
    forwarder(StreamEnvelope(type="agent.task_start", correlation_id="corr-1", payload={}))

    assert [(message["event"], message["step_id"]) for message in message_writer.messages] == [
        ("llm_fallback_skipped", 1),
        ("task_start", 2),
    ]
    assert message_writer.messages[0] == {
        "message_type": "agent_node_stream",
        "event": "llm_fallback_skipped",
        "step_id": 1,
        "is_final": False,
        "agent_id": 7,
        "data": {"message": "Fallback LLM was skipped: no API key."},
    }
