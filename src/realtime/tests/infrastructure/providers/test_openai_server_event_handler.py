"""OpenAI ServerEventHandler: forwards OpenAI Realtime events to the frontend, runs
tool calls, and records every event. The DB write is the recorded side effect."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from infrastructure.providers.openai.event_handlers.agent_server_event_handler import ServerEventHandler

pytestmark = pytest.mark.asyncio


@pytest.fixture
def db_write():
    with patch(
        "infrastructure.providers.openai.event_handlers.agent_server_event_handler.save_realtime_session_item_to_db",
        new_callable=AsyncMock,
    ) as write:
        yield write


@pytest.fixture
def client():
    sent: list[dict] = []

    async def send_client(payload):
        sent.append(payload)

    return SimpleNamespace(
        connection_key="test_conn", org_id=55, user_id=6, sent=sent, send_client=send_client, call_tool=AsyncMock()
    )


@pytest.fixture
def handler(client, db_write):
    return ServerEventHandler(client)


def _item(item_id) -> dict:
    return {"type": "conversation.item.created", "item": {"id": item_id, "type": "message"}}


@pytest.mark.parametrize(
    ("event", "forwarded"),
    [
        ({"type": "response.created", "response": {"id": "r1"}}, "same"),
        ({"type": "response.audio.delta", "delta": "abc123"}, "same"),
        ({"type": "session.created", "session": {}}, "same"),
        ({"type": "error", "error": {"message": "oops"}}, "same"),
        ({"type": "completely_unknown"}, "same"),
        # The GA API's event names are mapped to the beta names the frontend handles.
        ({"type": "response.output_audio.delta", "delta": "abc"}, {"type": "response.audio.delta", "delta": "abc"}),
        ({"type": "response.output_text.done", "text": "hi"}, {"type": "response.text.done", "text": "hi"}),
        (
            {"type": "conversation.item.added", "item": {"id": "msg_1"}},
            {"type": "conversation.item.created", "item": {"id": "msg_1"}},
        ),
        # The client's own wake-word handover echo is hidden from the UI.
        (_item("dont_show_it"), None),
        (_item("dont_show_it_abcdef1234567890"), None),
        ({"type": "conversation.item.added", "item": {"id": "dont_show_it_abc"}}, None),
        (_item("msg_abc"), "same"),
        (_item("item_ABC123"), "same"),
        (_item("fc_xyz789"), "same"),
        (_item(None), "same"),
        ({"type": "conversation.item.created", "item": {}}, "same"),
        ({"type": "response.function_call_arguments.delta", "delta": "{"}, None),
    ],
    ids=lambda value: value["type"] + (f":{value['item'].get('id')}" if "item" in value else "") if isinstance(value, dict) else None,
)
async def test_event_reaches_the_frontend(handler, client, db_write, event, forwarded):
    await handler.handle_event(event)

    expected = [] if forwarded is None else [event if forwarded == "same" else forwarded]
    assert client.sent == expected
    # Every event is recorded under the caller's org, whether or not it is shown.
    kwargs = db_write.await_args.kwargs
    assert (kwargs["data"], kwargs["connection_key"], kwargs["org_id"], kwargs["user_id"]) == (event, "test_conn", 55, 6)


async def test_finished_function_call_runs_the_tool_and_is_forwarded(handler, client, captured_log_messages):
    event = {
        "type": "response.function_call_arguments.done",
        "call_id": "call_42",
        "name": "search_tool",
        "arguments": json.dumps({"query": "my card number is 4111"}),
    }

    await handler.handle_event(event)

    client.call_tool.assert_awaited_once_with(
        call_id="call_42", tool_name="search_tool", tool_arguments={"query": "my card number is 4111"}
    )
    assert client.sent == [event]
    # The call is traceable in the logs, but the arguments may hold user data.
    assert any("search_tool" in message and "call_42" in message for message in captured_log_messages)
    assert not any("4111" in message for message in captured_log_messages)
