import httpx
import pytest

from foundation.transport.http import errors
from foundation.transport.http.client import AsyncClient, Client


def test_sync_client_returns_response_on_2xx():
    def handler(request):
        return httpx.Response(200, json={"ok": True})

    client = Client(transport=httpx.MockTransport(handler), base_url="https://example.test")
    response = client.request("GET", "/")
    assert response.json() == {"ok": True}


def test_sync_client_raises_typed_error_on_404():
    def handler(request):
        return httpx.Response(404, text="nope")

    client = Client(transport=httpx.MockTransport(handler), base_url="https://example.test")
    with pytest.raises(errors.ClientNotFoundError) as exc_info:
        client.request("GET", "/")
    assert exc_info.value.response.status_code == 404


def test_sync_client_raises_server_error_on_500():
    def handler(request):
        return httpx.Response(500, text="oops")

    client = Client(transport=httpx.MockTransport(handler), base_url="https://example.test")
    with pytest.raises(errors.ClientServerError):
        client.request("GET", "/")


def test_sync_client_raises_connection_error():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    client = Client(transport=httpx.MockTransport(handler), base_url="https://example.test")
    with pytest.raises(errors.ClientConnectionError):
        client.request("GET", "/")


def test_sync_client_raises_timeout_error():
    def handler(request):
        raise httpx.TimeoutException("boom", request=request)

    client = Client(transport=httpx.MockTransport(handler), base_url="https://example.test")
    with pytest.raises(errors.ClientTimeoutError):
        client.request("GET", "/")


@pytest.mark.asyncio
async def test_async_client_returns_response_on_2xx():
    def handler(request):
        return httpx.Response(200, json={"ok": True})

    client = AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test")
    response = await client.request("GET", "/")
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_async_client_raises_typed_error_on_500():
    def handler(request):
        return httpx.Response(500, text="oops")

    client = AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test")
    with pytest.raises(errors.ClientServerError):
        await client.request("GET", "/")


@pytest.mark.asyncio
async def test_async_client_raises_connection_error():
    async def handler(request):
        raise httpx.ConnectError("boom", request=request)

    client = AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test")
    with pytest.raises(errors.ClientConnectionError):
        await client.request("GET", "/")
