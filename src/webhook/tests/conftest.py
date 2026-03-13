import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from app.main import create_app
from app.services.redis_service import RedisService
from app.providers.base import AbstractTunnelProvider


@pytest.fixture
def mock_redis_service():
    redis_mock = AsyncMock(spec=RedisService)
    redis_mock.publish_webhook.return_value = None
    return redis_mock


@pytest.fixture
def mock_tunnel_provider():
    tunnel = AsyncMock(spec=AbstractTunnelProvider)
    tunnel.public_url = "https://mock-tunnel.ngrok.io"
    return tunnel


@pytest.fixture
def app(mock_webhook_service):
    return create_app(webhook_service=mock_webhook_service)


@pytest.fixture
def client(app, mock_redis_service):
    from app.controllers.webhook_routes import get_redis_service

    app.dependency_overrides[get_redis_service] = lambda: mock_redis_service
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
