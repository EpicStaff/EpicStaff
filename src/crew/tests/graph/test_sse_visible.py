from unittest.mock import MagicMock

import pytest
from dotdict import DotDict

from models.graph_models import StartMessageData
from services.graph.custom_message_writer import CustomSessionMessageWriter
from services.graph.events import StopEvent
from services.graph.nodes import BaseNode


def make_state(variables: dict) -> dict:
    return {
        "state_history": [],
        "variables": DotDict(variables),
        "system_variables": {},
    }


class _FakeFinishingNode(BaseNode):
    """Minimal concrete node used to exercise BaseNode.add_finish_message."""

    TYPE = "FAKE"

    def __init__(self, stream_config: dict | None = None):
        super().__init__(
            session_id=1,
            node_name="fake_node",
            stop_event=StopEvent(),
        )
        self.stream_config = stream_config

    async def execute(self, state, writer, execution_order, input_):
        return "output"


def test_add_finish_message_defaults_sse_visible_to_true():
    writer = MagicMock()
    message = CustomSessionMessageWriter.add_finish_message(
        session_id=1,
        node_name="node",
        writer=writer,
        output="result",
        execution_order=0,
        state=make_state({}),
    )

    assert message.message_data.sse_visible is True


def test_add_finish_message_respects_explicit_sse_visible_false():
    writer = MagicMock()
    message = CustomSessionMessageWriter.add_finish_message(
        session_id=1,
        node_name="node",
        writer=writer,
        output="result",
        execution_order=0,
        state=make_state({}),
        sse_visible=False,
    )

    assert message.message_data.sse_visible is False


def test_start_message_data_serializes_sse_visible_true():
    start_message_data = StartMessageData(input={"foo": "bar"})

    assert start_message_data.sse_visible is True


@pytest.mark.asyncio
async def test_node_with_final_reply_false_suppresses_finish_message():
    node = _FakeFinishingNode(stream_config={"final_reply": False})
    writer = MagicMock()
    state = make_state({})

    await node.run(state=state, writer=writer)

    finish_messages = [
        call.args[0].message_data
        for call in writer.call_args_list
        if call.args[0].message_data.message_type == "finish"
    ]

    assert len(finish_messages) == 1
    assert finish_messages[0].sse_visible is False


@pytest.mark.asyncio
async def test_node_without_stream_config_keeps_finish_message_visible():
    node = _FakeFinishingNode(stream_config=None)
    writer = MagicMock()
    state = make_state({})

    await node.run(state=state, writer=writer)

    finish_messages = [
        call.args[0].message_data
        for call in writer.call_args_list
        if call.args[0].message_data.message_type == "finish"
    ]

    assert len(finish_messages) == 1
    assert finish_messages[0].sse_visible is True
