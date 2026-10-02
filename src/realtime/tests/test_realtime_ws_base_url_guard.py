"""
A malformed per-org `rt_base_url` must be rejected cleanly at the WS boundary in
`root()`: `OpenaiSummarizationClient` validates the URL when it is built, so the
`ValueError` is caught there instead of escaping to uvicorn as an unhandled
ASGI exception.

Like `test_realtime_ws_org_id_guard.py`, these tests call `root()` directly with
a mocked WebSocket.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.shared.models import RealtimeAgentChatData
from infrastructure.persistence.connection_repository import ConnectionRepository
from tests.conftest import CONNECTION_KEY, TOKEN


def _make_chat_data(rt_base_url: str) -> RealtimeAgentChatData:
    return RealtimeAgentChatData.model_construct(
        connection_key=CONNECTION_KEY,
        org_id=1,
        rt_api_key="fake_key",
        rt_base_url=rt_base_url,
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


@pytest.mark.asyncio
async def test_root_rejects_scheme_less_rt_base_url(monkeypatch):
    from api import main as main_module

    monkeypatch.setattr(
        main_module,
        "introspect_token",
        lambda token: {"active": True, "user_id": 1, "org_ids": [1], "is_superadmin": False},
    )

    connection_key = "scheme-less-base-url-key"
    ConnectionRepository().save_connection(
        connection_key=connection_key, data=_make_chat_data("my-proxy.internal")
    )

    called = {"conversation_service": False}
    monkeypatch.setattr(
        main_module,
        "ConversationService",
        lambda *a, **kw: called.__setitem__("conversation_service", True),
    )

    ws = MagicMock()
    ws.query_params = {"token": TOKEN}
    ws.close = AsyncMock()

    await main_module.root(
        websocket=ws,
        model=None,
        connection_key=connection_key,
        db_session=None,
    )

    ws.close.assert_awaited_once_with(code=1011)
    assert called["conversation_service"] is False
