"""
`RealtimeAgentChatData.org_id` is a required field, so
every *current* construction path always populates it — but a raw
`AttributeError` deep inside `factory.create()` (or inside a
`save_realtime_session_item_to_db` call from a provider event handler) is
the wrong failure mode for a security-load-bearing field: if any future
construction path (or a stale/partial payload) ever produces a
`RealtimeAgentChatData` without `org_id`, the session must be rejected
cleanly at the WS boundary in `root()` (and in the Twilio voice-stream
handler), not blow up mid-session with an unhandled exception.

These tests call `root()` directly (rather than through a TestClient — this
env's httpx/starlette pin doesn't support ASGI TestClient websocket testing)
with a mocked FastAPI WebSocket, and simulate the "impossible in normal
operation" missing-org_id case via `model_construct` (bypassing validation,
since the field is required and this shape is not otherwise reachable
through the real converters). This proves the fail-fast guard added to
`api/main.py::root` catches it before ever reaching
`ConversationService`/`factory.create`.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.shared.models import RealtimeAgentChatData
from infrastructure.persistence.connection_repository import ConnectionRepository
from tests.conftest import CONNECTION_KEY, TOKEN


def _make_chat_data_without_org_id() -> RealtimeAgentChatData:
    """Simulate a payload missing `org_id` — bypasses validation via
    `model_construct`, since the field is required and this shape is not
    otherwise reachable through the real converters."""
    return RealtimeAgentChatData.model_construct(
        connection_key=CONNECTION_KEY,
        rt_api_key="fake_key",
        rt_model_name="test_model",
        wake_word="wake",
        voice="voice1",
        temperature=0.5,
        language="en",
        goal="assist user",
        backstory="helpful assistant",
        role="assistant",
        transcript_api_key=None,
        transcript_model_name=None,
        voice_recognition_prompt="say something",
        knowledge_collection_id=1,
        memory=True,
        stop_prompt="stop",
        tools=[],
        rt_provider="openai",
        input_audio_format="pcm16",
        output_audio_format="pcm16",
    )


def _make_ws(connection_key: str, token: str = TOKEN) -> MagicMock:
    ws = MagicMock()
    ws.query_params = {"token": token}
    ws.close = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_root_rejects_connection_missing_org_id(monkeypatch):
    """A RealtimeAgentChatData missing org_id must be rejected with a clean
    close(1011) — not surface as an AttributeError deep in factory.create."""
    from api import main as main_module

    monkeypatch.setattr(
        main_module,
        "introspect_token",
        lambda token: {
            "active": True,
            "user_id": 1,
            "org_ids": [1],
            "is_superadmin": False,
        },
    )

    connection_key = "missing-org-id-key"
    ConnectionRepository().save_connection(
        connection_key=connection_key, data=_make_chat_data_without_org_id()
    )

    called = {"conversation_service": False}
    monkeypatch.setattr(
        main_module,
        "ConversationService",
        lambda *a, **kw: called.__setitem__("conversation_service", True),
    )

    ws = _make_ws(connection_key)

    await main_module.root(
        websocket=ws,
        model=None,
        connection_key=connection_key,
        db_session=None,
    )

    ws.close.assert_awaited_once_with(code=1011)
    assert called["conversation_service"] is False


@pytest.mark.asyncio
async def test_root_rejects_connection_missing_org_id_even_for_superadmin(
    monkeypatch,
):
    """Superadmin bypasses the org-ownership *comparison* (short-circuits
    before ever touching `.org_id`) but must still be rejected by the
    unconditional presence check — this is exactly the gap that let the
    original AttributeError surface deep inside factory.create() instead
    of at the WS boundary."""
    from api import main as main_module

    monkeypatch.setattr(
        main_module,
        "introspect_token",
        lambda token: {
            "active": True,
            "user_id": 1,
            "org_ids": [],
            "is_superadmin": True,
        },
    )

    connection_key = "missing-org-id-key-superadmin"
    ConnectionRepository().save_connection(
        connection_key=connection_key, data=_make_chat_data_without_org_id()
    )

    called = {"conversation_service": False}
    monkeypatch.setattr(
        main_module,
        "ConversationService",
        lambda *a, **kw: called.__setitem__("conversation_service", True),
    )

    ws = _make_ws(connection_key)

    await main_module.root(
        websocket=ws,
        model=None,
        connection_key=connection_key,
        db_session=None,
    )

    ws.close.assert_awaited_once_with(code=1011)
    assert called["conversation_service"] is False
