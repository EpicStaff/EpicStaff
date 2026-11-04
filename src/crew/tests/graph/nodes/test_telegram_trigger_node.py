import pytest
from dotdict import DotDict

from services.graph.events import StopEvent
from services.graph.exceptions import NodeExecutionError
from services.graph.graph_session_manager_service import GraphSessionManagerService
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


def _telegram_node(variable_path: str = "variables.user_text") -> TelegramTriggerNode:
    return TelegramTriggerNode(
        session_id=1,
        node_name="New message #1 #31",
        stop_event=StopEvent(),
        field_list=[
            TelegramTriggerNodeFieldData(parent="message", field_name="text", variable_path=variable_path),
        ],
    )


async def _run_failing(payload, variable_path: str = "variables.user_text") -> tuple[str, list[str]]:
    """Run the node, expecting it to fail; return the session's error and the error cards."""
    messages = []
    state = {"variables": DotDict({"telegram_payload": payload}), "state_history": [], "system_variables": {}}
    with pytest.raises(NodeExecutionError) as raised:
        await _telegram_node(variable_path).run(state, writer=messages.append)
    details = [message.message_data.details for message in messages if message.message_data.message_type == "error"]
    return GraphSessionManagerService._public_session_error(1, raised.value), details


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"message": None}, id="parent-is-null"),
        pytest.param({"message": "hello"}, id="parent-isnt-an-object"),
        pytest.param(None, id="no-update"),
    ],
)
async def test_field_that_cant_be_read_is_named(payload):
    session_error, details = await _run_failing(payload)

    expected = (
        'Telegram Trigger node "New message #1": field "message.text" can\'t be read from the update. '
        "Check the field path."
    )
    assert details == [expected]
    assert session_error == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("variable_path", "suggestion"),
    [
        pytest.param("context.user_text", "variables.user_text", id="not-under-variables"),
        pytest.param("", "variables.value", id="empty"),
    ],
)
async def test_variable_path_that_isnt_a_flow_variable_is_named(variable_path, suggestion):
    session_error, details = await _run_failing({"message": {"text": "hi"}}, variable_path)

    expected = (
        f'Telegram Trigger node "New message #1": variable path "{variable_path}" must be a flow '
        f"variable, like {suggestion}."
    )
    assert details == [expected]
    assert session_error == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variable_path",
    [
        pytest.param("variables.items[5]", id="index-into-a-non-list"),
        pytest.param("variables.telegram_payload.message.text.words", id="through-a-string"),
        pytest.param("variables.telegram_payload.message.text[0]", id="index-into-a-string"),
    ],
)
async def test_flow_variable_path_that_doesnt_exist_is_named(variable_path):
    session_error, details = await _run_failing({"message": {"text": "hi"}}, variable_path)

    expected = (
        f'Telegram Trigger node "New message #1": variable path "{variable_path}" doesn\'t exist. '
        "Check the variable path."
    )
    assert details == [expected]
    assert session_error == expected
