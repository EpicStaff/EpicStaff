import os

import pytest
from src.shared.models import LocalhostConfigData, NgrokConfigData

from app.core.settings import settings


async def _published_tunnel_urls(redis_service) -> dict[str, str]:
    """The tunnel URLs Django reads to show each webhook's public address."""
    return await redis_service.client.hgetall(settings.TUNNEL_URLS_HASH_KEY)


@pytest.mark.parametrize(
    ("domain", "expected_url"),
    [
        ("my-local.dev", "http://my-local.dev"),
        (None, f"http://{settings.LOCALHOST_TARGET_HOST}:{settings.LOCALHOST_TARGET_PORT}"),
    ],
    ids=["custom-domain", "target-host-and-port"],
)
async def test_localhost_tunnel_url_is_published_and_removed_on_unregister(
    tunnel_registry, redis_service, domain, expected_url
):
    config = LocalhostConfigData(name="hook", org_id=1, domain=domain)

    await tunnel_registry.register(config)

    assert await _published_tunnel_urls(redis_service) == {config.unique_id: expected_url}

    await tunnel_registry.unregister(config.unique_id)

    assert await _published_tunnel_urls(redis_service) == {}


async def test_ngrok_tunnel_is_started_with_its_config_and_fully_torn_down(
    tunnel_registry, redis_service, ngrok_environment
):
    config = NgrokConfigData(
        name="hook", org_id=1, auth_token="secret-token", domain="my.ngrok.app", region="us"
    )

    await tunnel_registry.register(config)

    connect_call = ngrok_environment.ngrok.connect.call_args
    assert connect_call.args == (
        f"{settings.NGROK_TARGET_HOST}:{settings.NGROK_TARGET_PORT}",
        "http",
    )
    assert connect_call.kwargs["domain"] == "my.ngrok.app"
    pyngrok_config = connect_call.kwargs["pyngrok_config"]
    assert pyngrok_config.auth_token == "secret-token"
    assert pyngrok_config.region == "us"
    assert await _published_tunnel_urls(redis_service) == {
        config.unique_id: "https://real-ngrok-url.com"
    }

    await tunnel_registry.unregister(config.unique_id)

    ngrok_environment.ngrok.disconnect.assert_called_once_with(
        "https://real-ngrok-url.com", pyngrok_config=pyngrok_config
    )
    ngrok_environment.process.kill_process.assert_called_once_with(pyngrok_config.ngrok_path)
    assert not os.path.exists(pyngrok_config.ngrok_path)
    assert list(ngrok_environment.temp_root.iterdir()) == []
    assert await _published_tunnel_urls(redis_service) == {}
