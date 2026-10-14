import pytest
from dotdict import DotDict

from services.graph.events import StopEvent
from services.graph.nodes.telegram_trigger_node import TelegramTriggerNode
from src.shared.models import TelegramTriggerNodeFieldData


@pytest.mark.asyncio
async def test_payload_fields_are_mapped_to_their_variables_and_missing_ones_to_none():
    node = TelegramTriggerNode(
        session_id=1,
        node_name="telegram",
        stop_event=StopEvent(),
        field_list=[
            TelegramTriggerNodeFieldData(parent="message", field_name="text", variable_path="variables.user_text"),
            TelegramTriggerNodeFieldData(parent="message", field_name="message_id", variable_path="variables.msg_id"),
            # One trigger may receive different update kinds; an absent field is not an error.
            TelegramTriggerNodeFieldData(parent="callback_query", field_name="data", variable_path="variables.button"),
        ],
    )
    payload = {"message": {"text": "Hello world", "message_id": 123}}
    state = {"variables": DotDict({"telegram_payload": payload}), "state_history": [], "system_variables": {}}

    updated = await node.run(state, writer=lambda message: None)

    assert updated["variables"].deep_dump() == {
        "telegram_payload": payload,
        "user_text": "Hello world",
        "msg_id": 123,
        "button": None,
    }
