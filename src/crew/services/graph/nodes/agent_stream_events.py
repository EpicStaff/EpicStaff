from typing import Any

from langgraph.types import StreamWriter

from services.graph.custom_message_writer import CustomSessionMessageWriter
from src.shared.redis_streams import StreamEnvelope

KNOWLEDGE_SEARCH_ENVELOPE_TYPE = "agent.knowledge_search"

STREAM_EVENT_BY_ENVELOPE_TYPE = {
    "agent.tool_call": "tool_call",
    "agent.tool_result": "tool_result",
    "agent.task_start": "task_start",
    "agent.task_finish": "task_finish",
}


class AgentStreamEventForwarder:
    """Translates agent-service ``StreamEnvelope``s into graph session messages.

    Shared by ``AgentNode`` and ``TaskNode``, both of which dispatch work to the
    agent service and forward its live events onto the session's custom
    message writer, differing only in the generic stream message type they
    emit (e.g. ``"agent_node_stream"`` vs ``"task_node_stream"``).
    """

    def __init__(
        self,
        custom_session_message_writer: CustomSessionMessageWriter,
        session_id: int,
        node_name: str,
        writer: StreamWriter,
        execution_order: int,
        stream_message_type: str,
    ):
        self._custom_session_message_writer = custom_session_message_writer
        self._session_id = session_id
        self._node_name = node_name
        self._writer = writer
        self._execution_order = execution_order
        self._stream_message_type = stream_message_type
        self._step_id = 0

    def __call__(self, envelope: StreamEnvelope) -> None:
        if envelope.type == KNOWLEDGE_SEARCH_ENVELOPE_TYPE:
            self._write_message(
                {
                    "message_type": "extracted_chunks",
                    "sse_visible": True,
                    **envelope.payload,
                }
            )
            return

        event = STREAM_EVENT_BY_ENVELOPE_TYPE.get(envelope.type)
        if event is None:
            return

        self._step_id += 1
        self._write_message(
            {
                "message_type": self._stream_message_type,
                "event": event,
                "step_id": self._step_id,
                "is_final": False,
                "sse_visible": True,
                "data": envelope.payload,
            }
        )

    def _write_message(self, message_data: dict[str, Any]) -> None:
        self._custom_session_message_writer.add_custom_message(
            session_id=self._session_id,
            node_name=self._node_name,
            writer=self._writer,
            execution_order=self._execution_order,
            message_data=message_data,
        )
