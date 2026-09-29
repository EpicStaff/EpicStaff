import asyncio
import json

import httpx
import pytest

from clients import key_value as key_value_module
from clients.errors import (
    ClientBadGatewayError,
    ClientNotAvailableError,
    ClientTimeoutError,
    ClientValidationError,
)
from clients.key_value import KEEPALIVE_EXPIRY_SECONDS, RETRY_BACKOFF_SECONDS, KeyValueClient

BASE_URL = "http://django:8000/api/"


async def _started(handler) -> KeyValueClient:
    client = KeyValueClient(BASE_URL, api_key="secret", timeout=5.0, transport=httpx.MockTransport(handler))
    await client.start()
    return client


@pytest.mark.asyncio
async def test_read_posts_keys_with_system_key_and_returns_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers["X-API-Key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"values": {"a": 1}, "table_name": "Customers"})

    client = await _started(handler)
    assert await client.read(7, 3, ["a", "b"]) == {"values": {"a": 1}, "table_name": "Customers"}
    await client.stop()

    assert seen["url"] == f"{BASE_URL}internal/sessions/7/key-value-tables/3/read/"
    assert seen["api_key"] == "secret"
    assert seen["body"] == {"keys": ["a", "b"]}


@pytest.mark.asyncio
async def test_write_sends_entries_and_returns_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"written": 1, "created": ["k"], "table_name": "Customers"})

    client = await _started(handler)
    assert await client.write(7, 3, {"k": {"v": 1}}) == {
        "written": 1,
        "created": ["k"],
        "table_name": "Customers",
    }
    assert seen["url"].endswith("/key-value-tables/3/write/")
    assert seen["body"] == {"entries": {"k": {"v": 1}}}


@pytest.mark.asyncio
async def test_delete_sends_keys_and_returns_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"deleted": 1, "table_name": "Customers"})

    client = await _started(handler)
    assert await client.delete(7, 3, ["k"]) == {"deleted": 1, "table_name": "Customers"}
    assert seen["body"] == {"keys": ["k"]}


@pytest.fixture
def waits(monkeypatch):
    """Record retry waits instead of sleeping."""
    recorded = []

    async def fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(key_value_module.asyncio, "sleep", fake_sleep)
    yield recorded


@pytest.mark.asyncio
async def test_4xx_raises_validation_error_with_django_message_without_retrying(waits):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404, json={"status_code": 404, "code": "x", "message": "Key-value table 3 not found."})

    client = await _started(handler)
    with pytest.raises(ClientValidationError, match="Key-value table 3 not found."):
        await client.read(7, 3, ["a"])
    assert len(calls) == 1
    assert waits == []


@pytest.mark.asyncio
async def test_5xx_raises_bad_gateway_without_retrying(waits):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500, text="boom")

    client = await _started(handler)
    with pytest.raises(ClientBadGatewayError):
        await client.read(7, 3, ["a"])
    assert len(calls) == 1
    assert waits == []


@pytest.mark.asyncio
async def test_timeout_raises_client_timeout_without_retrying(waits):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("slow", request=request)

    client = await _started(handler)
    with pytest.raises(ClientTimeoutError):
        await client.read(7, 3, ["a"])
    assert len(calls) == 1
    assert waits == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [httpx.ReadError, httpx.RemoteProtocolError],
    ids=["read_error", "remote_protocol_error"],
)
async def test_connection_reset_is_retried_and_the_retry_response_is_returned(waits, error):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise error("reset", request=request)
        return httpx.Response(200, json={"written": 1, "created": ["k"], "table_name": "Customers"})

    client = await _started(handler)
    assert await client.write(7, 3, {"k": 1}) == {"written": 1, "created": ["k"], "table_name": "Customers"}
    assert len(calls) == 2
    assert waits == [RETRY_BACKOFF_SECONDS[0]]


@pytest.mark.asyncio
async def test_connection_failing_on_every_attempt_raises_not_available_after_all_retries(waits):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("refused", request=request)

    client = await _started(handler)
    with pytest.raises(ClientNotAvailableError, match="Django is unreachable."):
        await client.delete(7, 3, ["k"])
    assert len(calls) == 4
    assert waits == [0.2, 0.4, 0.8]


def test_keepalive_expires_before_djangos_two_second_server_keepalive():
    assert KEEPALIVE_EXPIRY_SECONDS < 2


@pytest.mark.asyncio
async def test_idle_connection_is_replaced_after_keepalive_expiry(monkeypatch):
    # A real socket: MockTransport bypasses the connection pool this test is about.
    monkeypatch.setattr(key_value_module, "KEEPALIVE_EXPIRY_SECONDS", 0.3)
    accepted = []
    body = b'{"written": 1, "created": [], "table_name": "Customers"}'

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        accepted.append(writer)
        try:
            while head := await reader.readuntil(b"\r\n\r\n"):
                length = next(
                    int(line.split(b":", 1)[1])
                    for line in head.split(b"\r\n")
                    if line.lower().startswith(b"content-length:")
                )
                await reader.readexactly(length)
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
                )
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = KeyValueClient(f"http://127.0.0.1:{port}/api/", api_key="secret", timeout=5.0)
    await client.start()
    try:
        await client.write(7, 3, {"k": 1})
        await client.write(7, 3, {"k": 1})
        # Within the expiry the connection is reused, so pooling is still on.
        assert len(accepted) == 1
        await asyncio.sleep(0.6)
        await client.write(7, 3, {"k": 1})
        assert len(accepted) == 2
    finally:
        await client.stop()
        server.close()
        await server.wait_closed()


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

    client = KeyValueClient(BASE_URL, api_key=None, timeout=5.0, transport=httpx.MockTransport(handler))
    await client.start()

    with pytest.raises(ClientNotAvailableError, match="DJANGO_API_KEY is not configured"):
        await call(client)
    await client.stop()

    assert sent == []
