import pytest
from unittest.mock import AsyncMock
from app.providers.tunnels.localhost_tunnel import LocalhostTunnel


@pytest.mark.asyncio
async def test_connect_uses_domain_when_provided():
    provider = LocalhostTunnel(port=8009, host="localhost", domain="my-local.dev")

    await provider.connect()

    assert provider.public_url == "http://my-local.dev"


@pytest.mark.asyncio
async def test_connect_builds_url_from_host_port_when_no_domain():
    provider = LocalhostTunnel(port=8009, host="localhost")

    await provider.connect()

    assert provider.public_url == "http://localhost:8009"


@pytest.mark.asyncio
async def test_connect_sets_is_running():
    provider = LocalhostTunnel(port=8009, host="localhost")

    await provider.connect()

    assert provider.is_active is True


@pytest.mark.asyncio
async def test_connect_calls_on_url_set_callback():
    callback = AsyncMock()
    provider = LocalhostTunnel(port=8009, host="localhost")
    provider._on_url_set = callback

    await provider.connect()

    callback.assert_called_once_with("http://localhost:8009")


@pytest.mark.asyncio
async def test_connect_calls_on_url_set_with_domain():
    callback = AsyncMock()
    provider = LocalhostTunnel(port=8009, host="localhost", domain="my-local.dev")
    provider._on_url_set = callback

    await provider.connect()

    callback.assert_called_once_with("http://my-local.dev")


@pytest.mark.asyncio
async def test_disconnect_clears_public_url():
    provider = LocalhostTunnel(port=8009, host="localhost")
    await provider.connect()

    await provider.disconnect()

    assert provider.public_url is None


@pytest.mark.asyncio
async def test_disconnect_sets_is_running_false():
    provider = LocalhostTunnel(port=8009, host="localhost")
    await provider.connect()

    await provider.disconnect()

    assert provider.is_active is False


@pytest.mark.asyncio
async def test_is_connected_true_after_connect():
    provider = LocalhostTunnel(port=8009, host="localhost")

    await provider.connect()

    assert provider.is_connected is True


@pytest.mark.asyncio
async def test_is_connected_false_after_disconnect():
    provider = LocalhostTunnel(port=8009, host="localhost")
    await provider.connect()

    await provider.disconnect()

    assert provider.is_connected is False


@pytest.mark.asyncio
async def test_on_url_set_not_called_when_not_set():
    provider = LocalhostTunnel(port=8009, host="localhost")

    # Should not raise even without a callback
    await provider.connect()

    assert provider.public_url == "http://localhost:8009"
