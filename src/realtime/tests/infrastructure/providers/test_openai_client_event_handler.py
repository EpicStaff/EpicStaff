"""
Tests for OpenAI ClientEventHandler event routing.

Regression coverage for a code-review finding: `handle_event` writes every
client-originated (frontend -> OpenAI) event to `realtime_session_items` via
`save_realtime_session_item_to_db`, and must forward `org_id` from the client
so those rows are tenant-scoped (security finding #33) — same as the
server-event-handler counterpart.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from infrastructure.providers.openai.event_handlers.agent_client_event_handler import (
    ClientEventHandler,
)

_DB_PATCH = "infrastructure.providers.openai.event_handlers.agent_client_event_handler.save_realtime_session_item_to_db"


@pytest.fixture
def client():
    c = MagicMock()
    c.connection_key = "test_conn"
    c.org_id = 44
    c.user_id = 88
    c.send_server = AsyncMock()
    return c


@pytest.fixture
def handler(client):
    return ClientEventHandler(client)


@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_handle_event_forwards_org_id_to_db_write(mock_db, handler, client):
    data = {"type": "input_audio_buffer.append", "audio": "abc"}
    await handler.handle_event(data)

    mock_db.assert_awaited_once()
    _, kwargs = mock_db.call_args
    assert kwargs.get("connection_key") == "test_conn"
    assert kwargs.get("org_id") == 44
    assert kwargs.get("user_id") == 88
