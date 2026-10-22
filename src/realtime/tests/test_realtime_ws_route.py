"""The browser realtime websocket `/realtime/`: who may attach to a prepared session.

`root()` is called directly with a stand-in WebSocket (this env's starlette pin has no
working ASGI websocket TestClient). Token introspection is Django's, an external call,
so it is replaced; so is ConversationService, which would connect to the AI provider.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.persistence.connection_repository import ConnectionRepository
from src.shared.models import RealtimeAgentChatData
from tests.conftest import TOKEN

pytestmark = pytest.mark.asyncio

MEMBER = {"active": True, "user_id": 1, "org_ids": [1], "is_superadmin": False}
OTHER_ORG_MEMBER = {"active": True, "user_id": 2, "org_ids": [2], "is_superadmin": False}
SUPERADMIN = {"active": True, "user_id": 3, "org_ids": [], "is_superadmin": True}


def _chat_data(connection_key: str, **overrides) -> RealtimeAgentChatData:
    # model_construct: some rows need shapes validation would reject (no org_id).
    return RealtimeAgentChatData.model_construct(
        **{
            "connection_key": connection_key,
            "org_id": 1,
            "rt_api_key": "fake_key",
            "rt_base_url": None,
            "rt_model_name": "test_model",
            "wake_word": "wake",
            "voice": "voice1",
            "temperature": 0.5,
            "language": "en",
            "goal": "assist user",
            "backstory": "helpful assistant",
            "role": "assistant",
            "transcript_api_key": None,
            "transcript_model_name": None,
            "voice_recognition_prompt": "say something",
            "knowledge_collection_id": 1,
            "memory": True,
            "stop_prompt": "stop",
            "tools": [],
            "rt_provider": "openai",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            **overrides,
        }
    )


@pytest.fixture
def started_sessions(monkeypatch):
    from api import main as main_module

    sessions = []

    class RecordingConversationService:
        def __init__(self, **kwargs):
            self.chat_data = kwargs["realtime_agent_chat_data"]

        async def execute(self):
            sessions.append(self.chat_data.connection_key)

    monkeypatch.setattr(main_module, "ConversationService", RecordingConversationService)
    return sessions


async def _connect(monkeypatch, user_info, connection_key="key", token=TOKEN, saved=None):
    from api import main as main_module

    monkeypatch.setattr(main_module, "introspect_token", lambda token: user_info)
    if saved is not None:
        ConnectionRepository().save_connection(connection_key=saved.connection_key, data=saved)
    ws = MagicMock()
    ws.query_params = {"token": token} if token else {}
    ws.close = AsyncMock()
    await main_module.root(websocket=ws, model=None, connection_key=connection_key, db_session=None)
    return ws


@pytest.mark.parametrize(
    ("user_info", "token", "connection_key", "saved", "close_code"),
    [
        pytest.param(MEMBER, None, "k-no-token", _chat_data("k-no-token"), 1008, id="no-token"),
        pytest.param(None, TOKEN, "k-bad-token", _chat_data("k-bad-token"), 1008, id="token-rejected-by-django"),
        pytest.param(MEMBER, TOKEN, None, None, 1008, id="no-connection-key"),
        pytest.param(MEMBER, TOKEN, "k-unknown", None, 1011, id="unknown-connection-key"),
        # Cross-org: the session belongs to an org this user is not a member of.
        pytest.param(OTHER_ORG_MEMBER, TOKEN, "k-cross-org", _chat_data("k-cross-org"), 1008, id="other-orgs-session"),
        # A payload without org_id must never start an unscoped session — not even for a superadmin.
        pytest.param(MEMBER, TOKEN, "k-no-org", _chat_data("k-no-org", org_id=None), 1011, id="session-without-org"),
        pytest.param(SUPERADMIN, TOKEN, "k-no-org-sa", _chat_data("k-no-org-sa", org_id=None), 1011, id="session-without-org-superadmin"),
        # A malformed per-org base URL is refused cleanly instead of escaping to uvicorn.
        pytest.param(MEMBER, TOKEN, "k-bad-url", _chat_data("k-bad-url", rt_base_url="my-proxy.internal"), 1011, id="scheme-less-base-url"),
    ],
)
async def test_connection_is_refused_before_any_session_starts(
    monkeypatch, started_sessions, user_info, token, connection_key, saved, close_code
):
    ws = await _connect(monkeypatch, user_info, connection_key, token, saved)

    ws.close.assert_awaited_once_with(code=close_code)
    assert started_sessions == []


@pytest.mark.parametrize("user_info", [MEMBER, SUPERADMIN], ids=["org-member", "superadmin"])
async def test_allowed_user_starts_the_session_once(monkeypatch, started_sessions, user_info):
    key = f"k-ok-{user_info['user_id']}"
    first = await _connect(monkeypatch, user_info, key, saved=_chat_data(key))
    # The connection key is single-use: a second attach with it finds nothing.
    second = await _connect(monkeypatch, user_info, key)

    first.close.assert_not_awaited()
    assert started_sessions == [key]
    second.close.assert_awaited_once_with(code=1011)
