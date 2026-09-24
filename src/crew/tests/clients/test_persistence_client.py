import json

import httpx
import pytest

from clients.errors import (
    ClientBadGatewayError,
    ClientNotAvailableError,
    ClientTimeoutError,
    ClientValidationError,
)
from clients.persistence import PersistenceClient

BASE_URL = "http://django:8000/api/"


async def _started(handler) -> PersistenceClient:
    client = PersistenceClient(BASE_URL, api_key="secret", timeout=5.0, transport=httpx.MockTransport(handler))
    await client.start()
    return client


@pytest.mark.asyncio
async def test_read_posts_keys_with_system_key_and_returns_values():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers["X-API-Key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"values": {"a": 1}})

    client = await _started(handler)
    assert await client.read(7, 3, ["a", "b"]) == {"a": 1}
    await client.stop()

    assert seen["url"] == f"{BASE_URL}internal/sessions/7/persistence-tables/3/read/"
    assert seen["api_key"] == "secret"
    assert seen["body"] == {"keys": ["a", "b"]}


@pytest.mark.asyncio
async def test_write_sends_entries():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"written": 1})

    client = await _started(handler)
    await client.write(7, 3, {"k": {"v": 1}})
    assert seen["url"].endswith("/persistence-tables/3/write/")
    assert seen["body"] == {"entries": {"k": {"v": 1}}}


@pytest.mark.asyncio
async def test_delete_sends_keys():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"deleted": 1})

    client = await _started(handler)
    await client.delete(7, 3, ["k"])
    assert seen["body"] == {"keys": ["k"]}


@pytest.mark.asyncio
async def test_4xx_raises_validation_error_with_django_message():
    def handler(request):
        return httpx.Response(404, json={"status_code": 404, "code": "x", "message": "Persistence table 3 not found."})

    client = await _started(handler)
    with pytest.raises(ClientValidationError, match="Persistence table 3 not found."):
        await client.read(7, 3, ["a"])


@pytest.mark.asyncio
async def test_5xx_raises_bad_gateway():
    client = await _started(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(ClientBadGatewayError):
        await client.read(7, 3, ["a"])


@pytest.mark.asyncio
async def test_timeout_raises_client_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    client = await _started(handler)
    with pytest.raises(ClientTimeoutError):
        await client.read(7, 3, ["a"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda client: client.read(7, 3, ["a"]),
        lambda client: client.write(7, 3, {"a": 1}),
        lambda client: client.delete(7, 3, ["a"]),
    ],
    ids=["read", "write", "delete"],
)
async def test_missing_api_key_starts_and_fails_calls_without_sending(call):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={"values": {}})

    client = PersistenceClient(BASE_URL, api_key=None, timeout=5.0, transport=httpx.MockTransport(handler))
    await client.start()

    with pytest.raises(ClientNotAvailableError, match="DJANGO_API_KEY is not configured"):
        await call(client)
    await client.stop()

    assert sent == []
