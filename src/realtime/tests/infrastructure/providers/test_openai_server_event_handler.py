"""
Tests for OpenAI ServerEventHandler event routing.
`save_realtime_session_item_to_db` is patched out to avoid DB dependency.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from infrastructure.providers.openai.event_handlers.agent_server_event_handler import (
    ServerEventHandler,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    c = MagicMock()
    c.connection_key = "test_conn"
    c.send_client = AsyncMock()
    c.call_tool = AsyncMock()
    return c


@pytest.fixture
def handler(client):
    return ServerEventHandler(client)


# ---------------------------------------------------------------------------
# default_handler — forwards event to client.send_client
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("infrastructure.providers.openai.event_handlers.agent_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_default_handler_forwards_to_send_client(mock_db, handler, client):
    data = {"type": "response.created", "response": {"id": "r1"}}
    await handler.handle_event(data)
    client.send_client.assert_awaited_once_with(data)


@pytest.mark.asyncio
@patch("infrastructure.providers.openai.event_handlers.agent_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_audio_delta_forwarded(mock_db, handler, client):
    data = {"type": "response.audio.delta", "delta": "abc123"}
    await handler.handle_event(data)
    client.send_client.assert_awaited_once_with(data)


@pytest.mark.asyncio
@patch("infrastructure.providers.openai.event_handlers.agent_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_session_created_forwarded(mock_db, handler, client):
    data = {"type": "session.created", "session": {}}
    await handler.handle_event(data)
    client.send_client.assert_awaited_once_with(data)


@pytest.mark.asyncio
@patch("infrastructure.providers.openai.event_handlers.agent_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_handle_event_forwards_org_id_to_db_write(mock_db, handler, client):
    client.org_id = 55
    data = {"type": "session.created", "session": {}}
    await handler.handle_event(data)
    _, kwargs = mock_db.call_args
    assert kwargs.get("org_id") == 55


# ---------------------------------------------------------------------------
# handle_error — logs and forwards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("infrastructure.providers.openai.event_handlers.agent_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_error_event_forwarded(mock_db, handler, client):
    data = {"type": "error", "error": {"message": "oops"}}
    await handler.handle_event(data)
    client.send_client.assert_awaited_once_with(data)


# ---------------------------------------------------------------------------
# handle_function_call_done — calls tool and forwards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("infrastructure.providers.openai.event_handlers.agent_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_function_call_done_calls_tool(mock_db, handler, client):
    data = {
        "type": "response.function_call_arguments.done",
        "call_id": "call_1",
        "name": "search_tool",
        "arguments": json.dumps({"query": "hello"}),
    }
    await handler.handle_event(data)
    client.call_tool.assert_awaited_once_with(
        call_id="call_1",
        tool_name="search_tool",
        tool_arguments={"query": "hello"},
    )


@pytest.mark.asyncio
@patch("infrastructure.providers.openai.event_handlers.agent_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_function_call_done_also_forwards_to_client(mock_db, handler, client):
    data = {
        "type": "response.function_call_arguments.done",
        "call_id": "c1",
        "name": "t",
        "arguments": "{}",
    }
    await handler.handle_event(data)
    client.send_client.assert_awaited_once_with(data)


# ---------------------------------------------------------------------------
# conversation_item_created_handler — skips "dont_show_it" id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("infrastructure.providers.openai.event_handlers.agent_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_conversation_item_skips_dont_show_it(mock_db, handler, client):
    data = {
        "type": "conversation.item.created",
        "item": {"id": "dont_show_it"},
    }
    await handler.handle_event(data)
    client.send_client.assert_not_awaited()


@pytest.mark.asyncio
@patch("infrastructure.providers.openai.event_handlers.agent_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_conversation_item_forwards_normal_item(mock_db, handler, client):
    data = {
        "type": "conversation.item.created",
        "item": {"id": "msg_abc", "type": "message"},
    }
    await handler.handle_event(data)
    client.send_client.assert_awaited_once_with(data)


# ---------------------------------------------------------------------------
# Unknown event type — forwarded as default
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("infrastructure.providers.openai.event_handlers.agent_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_unknown_event_forwarded(mock_db, handler, client):
    data = {"type": "completely_unknown"}
    await handler.handle_event(data)
    client.send_client.assert_awaited_once_with(data)


# ---------------------------------------------------------------------------
# save_realtime_session_item_to_db is always called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("infrastructure.providers.openai.event_handlers.agent_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_db_save_called_for_every_event(mock_db, handler):
    await handler.handle_event({"type": "response.done"})
    mock_db.assert_awaited_once()
