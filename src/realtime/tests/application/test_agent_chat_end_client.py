"""AgentChatEndClient reports a finished chat to Django and never raises."""

import json

import httpx
import pytest

from application.agent_chat_end_client import AgentChatEndClient

pytestmark = pytest.mark.asyncio


def _client_talking_to(monkeypatch, handler) -> AgentChatEndClient:
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    return AgentChatEndClient("http://django_app:8000/api", "system-key")


def _connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("unreachable")


async def test_end_chat_posts_key_rounded_duration_and_reason(monkeypatch):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"detail": "Updated"})

    client = _client_talking_to(monkeypatch, handler)

    await client.end_chat(connection_key="abc", duration=12.3456, end_reason="completed")

    (request,) = requests
    assert str(request.url) == "http://django_app:8000/api/realtime-agent-chats/end/"
    assert request.headers["x-api-key"] == "system-key"
    assert json.loads(request.content) == {
        "connection_key": "abc",
        "duration_seconds": 12.35,
        "end_reason": "completed",
    }


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500, text="boom"),
        lambda request: httpx.Response(404, json={"detail": "Not found"}),
        _connect_error,
    ],
    ids=["server-error", "not-found", "connection-error"],
)
async def test_end_chat_failure_is_swallowed(monkeypatch, handler):
    client = _client_talking_to(monkeypatch, handler)

    await client.end_chat(connection_key="abc", duration=1.0, end_reason="error")
