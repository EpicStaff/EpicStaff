import pytest
from dotdict import DotDict

from services.graph.events import StopEvent
from services.graph.exceptions import InvalidStatePathError, NodeConfigurationError
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


@pytest.mark.asyncio
async def test_underscore_variable_path_fails_with_a_public_message():
    node = TelegramTriggerNode(
        session_id=1,
        node_name="telegram",
        stop_event=StopEvent(),
        field_list=[
            TelegramTriggerNodeFieldData(parent="message", field_name="text", variable_path="variables.__class__.text"),
        ],
    )
    state = {"variables": DotDict({"telegram_payload": {"message": {"text": "hi"}}}), "state_history": [], "system_variables": {}}
    messages = []

    with pytest.raises(InvalidStatePathError):
        await node.run(state, writer=messages.append)

    error_details = [
        message.message_data.details for message in messages if message.message_data.message_type == "error"
    ]
    assert error_details == [
        "Variable path 'variables.__class__.text' is not allowed: path segments cannot start with '_'."
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "payload", "variables", "expected"),
    [
        (
            TelegramTriggerNodeFieldData(parent="message", field_name="text", variable_path="context.user_text"),
            {"message": {"text": "hi"}},
            {},
            'Telegram Trigger node "New message #1": variable path "context.user_text" isn\'t a flow variable.',
        ),
        (
            TelegramTriggerNodeFieldData(parent="message", field_name="text", variable_path="variables.tags[5]"),
            {"message": {"text": "hi"}},
            {"tags": ["only one"]},
            'Telegram Trigger node "New message #1": variable path "variables.tags[5]" doesn\'t exist.',
        ),
        (
            TelegramTriggerNodeFieldData(parent="message", field_name="text", variable_path="variables.user_text"),
            {"message": "not an object"},
            {},
            'Telegram Trigger node "New message #1": field "message.text" can\'t be read from the update.',
        ),
    ],
    ids=["path-outside-variables", "path-that-does-not-exist", "field-not-in-update"],
)
async def test_wrong_path_streams_the_fact(field, payload, variables, expected):
    node = TelegramTriggerNode(
        session_id=1, node_name="New message #1 #7", stop_event=StopEvent(), field_list=[field]
    )
    state = {
        "variables": DotDict({"telegram_payload": payload, **variables}),
        "state_history": [],
        "system_variables": {},
    }
    messages = []

    with pytest.raises((InvalidStatePathError, NodeConfigurationError)):
        await node.run(state, writer=messages.append)

    error_details = [
        message.message_data.details for message in messages if message.message_data.message_type == "error"
    ]
    assert error_details == [expected]
