import pytest
from fastapi.testclient import TestClient

from app.services.tunnel_registry import TunnelRegistry, get_tunnel_registry
from src.shared.models import LocalhostConfigData


class _FakeTunnel:
    def __init__(self, public_url):
        self._public_url = public_url


@pytest.fixture
def registered_client(app, mock_redis_service):
    """Client whose registry serves the request's own Host with one webhook."""
    from app.controllers.webhook_routes import get_redis_service

    registry = TunnelRegistry()
    config = LocalhostConfigData(name="registered-hook")
    registry._tunnel_pool[config.unique_id] = (_FakeTunnel("http://testserver"), config)

    app.dependency_overrides[get_redis_service] = lambda: mock_redis_service
    app.dependency_overrides[get_tunnel_registry] = lambda: registry
    with TestClient(app) as c:
        yield c, config
    app.dependency_overrides.clear()


def test_registered_path_resolves_to_its_own_config_id(
    registered_client, mock_redis_service
):
    client, config = registered_client

    response = client.post("/webhooks/registered-hook", json={"status": "ok"})

    assert response.status_code == 200
    assert response.json()["config_id"] == config.unique_id
    assert mock_redis_service.publish_webhook.call_args.kwargs["config_id"] == (
        config.unique_id
    )


def test_unknown_path_on_known_domain_returns_404_and_does_not_publish(
    registered_client, mock_redis_service
):
    client, _ = registered_client

    response = client.post("/webhooks/nope-not-a-hook", json={"status": "ok"})

    assert response.status_code == 404
    # No fabricated config_id of an unrelated webhook, and nothing published.
    assert "config_id" not in response.json()
    mock_redis_service.publish_webhook.assert_not_called()


def test_webhook_endpoint_success(client, mock_redis_service):
    webhook_path = "payment_success"
    payload = {"status": "ok"}

    response = client.post(f"/webhooks/{webhook_path}", json=payload)

    assert response.status_code == 200

    mock_redis_service.publish_webhook.assert_called_once()
    call_args = mock_redis_service.publish_webhook.call_args
    assert call_args.kwargs["path"] == webhook_path


def test_webhook_endpoint_query_params(client, mock_redis_service):
    webhook_path = "my-hook"

    query_params = {"a": "1", "b": "2"}

    response = client.post(
        f"/webhooks/{webhook_path}", params=query_params, json={"some": "data"}
    )

    assert response.status_code == 200

    mock_redis_service.publish_webhook.assert_called_once()
