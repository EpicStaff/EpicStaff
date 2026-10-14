"""OpenaiRealtimeAgentClient: the events it sends to the OpenAI Realtime API.

`send_server` (the provider websocket) is the external boundary, so it is a recorder.

Tool results on a live voice call used to leave the agent silent until the caller
spoke again: appending a `function_call_output` does not make OpenAI start a new
turn. The Twilio bridge has nobody driving that follow-up, so `call_tool()` requests
it there; the browser's vendored client already does, so it must not be duplicated.
"""

import pytest
from unittest.mock import AsyncMock

from infrastructure.providers.openai.event_handlers.agent_server_event_handler import (
    HIDDEN_ITEM_ID_PREFIX,
)
from infrastructure.providers.openai.openai_realtime_agent_client import OpenaiRealtimeAgentClient
from tests.conftest import PUBLIC_ERROR_REFERENCE, SECRET_SENTINEL


@pytest.fixture
def client():
    c = OpenaiRealtimeAgentClient(
        api_key="test_key",
        connection_key="conn_1",
        on_server_event=AsyncMock(),
        tool_manager_service=AsyncMock(),
    )
    c.send_server = AsyncMock()
    return c


def _sent(client) -> list[dict]:
    return [call.args[0] for call in client.send_server.await_args_list]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_fails", [False, True], ids=["tool-ok", "tool-fails"])
@pytest.mark.parametrize(
    ("is_twilio", "expected_types"),
    [(True, ["conversation.item.create", "response.create"]), (False, ["conversation.item.create"])],
    ids=["twilio", "browser"],
)
async def test_tool_output_is_sent_and_twilio_also_requests_the_next_turn(client, is_twilio, expected_types, tool_fails):
    client.is_twilio = is_twilio
    client.tool_manager_service.execute = (
        AsyncMock(side_effect=RuntimeError("tool failed")) if tool_fails else AsyncMock(return_value="ok")
    )

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    sent = _sent(client)
    # The output is appended before the response is requested.
    assert [event["type"] for event in sent] == expected_types
    assert sent[0]["item"]["call_id"] == "call_1"
    if not tool_fails:
        assert sent[0]["item"]["output"] == "ok"


@pytest.mark.asyncio
async def test_tool_failure_reaches_openai_without_the_exception_text(client, captured_log_messages):
    client.tool_manager_service.execute = AsyncMock(side_effect=RuntimeError(SECRET_SENTINEL))

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    (item_create,) = _sent(client)
    output = item_create["item"]["output"]
    assert output.startswith("Tool execution failed")
    assert SECRET_SENTINEL not in str(item_create)
    # Support can still find the detail in the logs under the reference the model saw.
    correlation_id = PUBLIC_ERROR_REFERENCE.search(output).group(1)
    (log,) = [message for message in captured_log_messages if correlation_id in message]
    assert SECRET_SENTINEL in log


@pytest.mark.parametrize(
    ("voice", "expected"), [("", "alloy"), (None, "alloy"), ("verse", "verse")], ids=["blank", "omitted", "explicit"]
)
def test_a_blank_voice_falls_back_to_alloy(voice, expected):
    """allow_blank serializers can send "", which errors or garbles audio at OpenAI."""
    kwargs = {} if voice is None else {"voice": voice}

    assert OpenaiRealtimeAgentClient(api_key="test_key", connection_key="conn_1", **kwargs).voice == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "expected"), [({"voice": ""}, "verse"), ({}, "verse"), ({"voice": "coral"}, "coral")],
    ids=["blank-override", "no-override", "explicit-override"],
)
async def test_session_update_voice_falls_back_to_the_clients_voice(client, config, expected):
    client.voice = "verse"

    await client.update_session(config=config)

    (event,) = _sent(client)
    assert event["session"]["audio"]["output"]["voice"] == expected


@pytest.mark.asyncio
async def test_wake_word_handover_text_is_sent_as_a_hidden_user_message_with_a_fresh_id(client):
    await client.send_conversation_item_to_server("hello")
    await client.send_conversation_item_to_server("hello")

    first, second = _sent(client)
    assert first["type"] == "conversation.item.create"
    assert {key: first["item"][key] for key in ("type", "role", "content")} == {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "hello"}],
    }
    # Hidden from the UI by the server handler; OpenAI rejects a reused id in a session,
    # and caps item ids at 32 characters.
    ids = [first["item"]["id"], second["item"]["id"]]
    assert all(item_id.startswith(HIDDEN_ITEM_ID_PREFIX) and len(item_id) <= 32 for item_id in ids)
    assert ids[0] != ids[1]
