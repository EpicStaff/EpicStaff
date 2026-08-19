from unittest.mock import MagicMock

from services.graph.nodes.agent_stream_events import AgentStreamEventForwarder
from src.shared.redis_streams import StreamEnvelope


def make_forwarder(
    custom_session_message_writer, stream_message_type="agent_node_stream"
):
    return AgentStreamEventForwarder(
        custom_session_message_writer=custom_session_message_writer,
        session_id=1,
        node_name="node_1",
        writer=MagicMock(),
        execution_order=0,
        stream_message_type=stream_message_type,
    )


def test_knowledge_search_envelope_writes_extracted_chunks_without_incrementing_step_id():
    writer = MagicMock()
    forwarder = make_forwarder(writer)

    forwarder(
        StreamEnvelope(
            type="agent.knowledge_search",
            correlation_id="corr-1",
            payload={"collection_id": 7, "chunks": [{"text": "chunk"}]},
        )
    )
    forwarder(
        StreamEnvelope(
            type="agent.tool_call",
            correlation_id="corr-1",
            payload={"id": "call_1"},
        )
    )

    calls = writer.add_custom_message.call_args_list
    assert len(calls) == 2

    knowledge_message = calls[0].kwargs["message_data"]
    assert knowledge_message == {
        "message_type": "extracted_chunks",
        "sse_visible": True,
        "collection_id": 7,
        "chunks": [{"text": "chunk"}],
    }

    tool_call_message = calls[1].kwargs["message_data"]
    assert tool_call_message["step_id"] == 1


def test_known_envelope_types_map_to_generic_stream_message_with_incrementing_step_id():
    writer = MagicMock()
    forwarder = make_forwarder(writer, stream_message_type="task_node_stream")

    envelope_types_and_expected_events = [
        ("agent.task_start", "task_start"),
        ("agent.tool_call", "tool_call"),
        ("agent.tool_result", "tool_result"),
        ("agent.task_finish", "task_finish"),
    ]
    for envelope_type, _ in envelope_types_and_expected_events:
        forwarder(
            StreamEnvelope(
                type=envelope_type, correlation_id="corr-1", payload={"key": "value"}
            )
        )

    calls = writer.add_custom_message.call_args_list
    assert len(calls) == 4

    written_messages = [call.kwargs["message_data"] for call in calls]
    assert [message["event"] for message in written_messages] == [
        "task_start",
        "tool_call",
        "tool_result",
        "task_finish",
    ]
    assert [message["step_id"] for message in written_messages] == [1, 2, 3, 4]
    for message in written_messages:
        assert message["message_type"] == "task_node_stream"
        assert message["is_final"] is False
        assert message["sse_visible"] is True
        assert message["data"] == {"key": "value"}


def test_unknown_envelope_type_writes_nothing():
    writer = MagicMock()
    forwarder = make_forwarder(writer)

    forwarder(
        StreamEnvelope(type="agent.heartbeat", correlation_id="corr-1", payload={})
    )

    writer.add_custom_message.assert_not_called()


def test_write_calls_use_configured_session_id_node_name_writer_and_execution_order():
    writer = MagicMock()
    stream_writer = MagicMock()
    forwarder = AgentStreamEventForwarder(
        custom_session_message_writer=writer,
        session_id=42,
        node_name="my_node",
        writer=stream_writer,
        execution_order=3,
        stream_message_type="agent_node_stream",
    )

    forwarder(
        StreamEnvelope(type="agent.tool_call", correlation_id="corr-1", payload={})
    )

    call = writer.add_custom_message.call_args
    assert call.kwargs["session_id"] == 42
    assert call.kwargs["node_name"] == "my_node"
    assert call.kwargs["writer"] is stream_writer
    assert call.kwargs["execution_order"] == 3
