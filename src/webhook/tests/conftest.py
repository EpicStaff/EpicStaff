import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import create_app
from app.providers.tunnels.base import AbstractTunnelProvider
from app.services.tunnel_registry import TunnelRegistry
from src.shared.models import BaseTunnelConfigData


@pytest.fixture
def mock_redis_service():
    redis_mock = AsyncMock()
    redis_mock.publish_webhook.return_value = None
    redis_mock.client.publish = AsyncMock(return_value=1)
    return redis_mock


@pytest.fixture
def mock_tunnel_provider():
    tunnel = AsyncMock(spec=AbstractTunnelProvider)
    tunnel.public_url = "https://mock-tunnel.ngrok.io"
    return tunnel


@pytest.fixture
def tunnel_registry():
    """A fresh, unpopulated `TunnelRegistry` for route-level tests.

    `handle_webhook` resolves the inbound path via
    `TunnelRegistry.resolve_by_path`, which only reads `_tunnel_pool` -- no
    real tunnel connection is needed, so tests populate it directly via
    `register_tunnel_path` instead of going through `register()` (which
    would call out to a real provider).
    """
    return TunnelRegistry()


@pytest.fixture
def register_tunnel_path(tunnel_registry):
    """Register a path in `tunnel_registry` without connecting a real tunnel.

    Returns the `BaseTunnelConfigData` used, so tests can assert against its
    `unique_id`/`auths`/`has_unauthenticated_node` if needed.
    """

    def _register(
        path: str,
        auths: list | None = None,
        has_unauthenticated_node: bool = False,
    ) -> BaseTunnelConfigData:
        config = BaseTunnelConfigData(
            name=path,
            auths=auths or [],
            has_unauthenticated_node=has_unauthenticated_node,
        )
        tunnel_registry._tunnel_pool[config.unique_id] = (None, config)
        return config

    return _register


@pytest.fixture
def app(mock_redis_service):
    with (
        patch(
            "app.main.get_redis_service", new=AsyncMock(return_value=mock_redis_service)
        ),
        patch("app.main.close_redis_connection", new=AsyncMock()),
        patch("app.main.listen_redis", new=AsyncMock()),
    ):
        yield create_app()


@pytest.fixture
def client(app, mock_redis_service, tunnel_registry):
    from app.controllers.webhook_routes import get_redis_service, get_tunnel_registry

    app.dependency_overrides[get_redis_service] = lambda: mock_redis_service
    app.dependency_overrides[get_tunnel_registry] = lambda: tunnel_registry
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
