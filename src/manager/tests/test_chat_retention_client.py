import json
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from helpers.chat_retention_client import ChatRetentionClient, ChatRetentionError

API_KEY = "internal-key-for-tests"
OLDER_THAN = datetime(2026, 7, 22, 3, 30, tzinfo=UTC)


def _client(handler) -> ChatRetentionClient:
    return ChatRetentionClient(
        "http://chat:8200/", API_KEY, transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_purge_posts_org_and_cutoff_with_the_internal_key():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"deleted": 42})

    deleted = await _client(handler).purge(org_id=5, older_than=OLDER_THAN)

    assert deleted == 42
    [request] = requests
    assert request.method == "POST"
    assert str(request.url) == "http://chat:8200/chat/internal/v1/retention/purge"
    assert request.headers["X-Internal-Api-Key"] == API_KEY
    assert json.loads(request.content) == {"org_id": 5, "older_than": "2026-07-22T03:30:00+00:00"}


@pytest.mark.asyncio
async def test_purge_sends_the_cutoff_in_utc():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"deleted": 0})

    kyiv_time = OLDER_THAN.astimezone(timezone(timedelta(hours=3)))
    await _client(handler).purge(org_id=5, older_than=kyiv_time)

    assert bodies[0]["older_than"] == "2026-07-22T03:30:00+00:00"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "message_part"),
    [
        (httpx.Response(401, json={"detail": "Invalid internal key"}), "401"),
        (httpx.Response(400, json={"detail": "older_than must not be in the future"}), "400"),
        (httpx.Response(500, text="Internal Server Error"), "500"),
        (httpx.Response(200, json={"purged": 3}), "deleted"),
        (httpx.Response(200, json={"deleted": "3"}), "deleted"),
        (httpx.Response(200, text="not json"), "deleted"),
    ],
)
async def test_purge_raises_on_a_rejected_or_malformed_response(response, message_part):
    with pytest.raises(ChatRetentionError, match=message_part):
        await _client(lambda request: response).purge(org_id=5, older_than=OLDER_THAN)


@pytest.mark.asyncio
async def test_purge_raises_when_chat_is_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name or service not known", request=request)

    with pytest.raises(ChatRetentionError, match="Name or service not known"):
        await _client(handler).purge(org_id=5, older_than=OLDER_THAN)

