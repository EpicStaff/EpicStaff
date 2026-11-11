import os

import pytest
from loguru import logger
from src.shared.models import (
    LocalhostConfigData,
    NgrokConfigData,
    WebhookConfigData,
    WebhookTriggerAuthData,
)
from transport_secrets import seal

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
        name="hook",
        org_id=1,
        auth_token=seal("secret-token"),
        domain="my.ngrok.app",
        region="us",
    )

    await tunnel_registry.register(config)

    connect_call = ngrok_environment.ngrok.connect.call_args
    # nginx's tunnel listener, which serves only /webhooks/ and /voice/: never port 80, which is
    # the whole of EpicStaff and would be published on the tunnel's public URL.
    assert connect_call.args == ("epicstaff-nginx:8083", "http")
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


@pytest.mark.parametrize(
    "auth_token", ["plain-ngrok-token", "gAAAAAforged-ngrok-token"], ids=["plaintext", "forged"]
)
async def test_ngrok_config_whose_token_cannot_be_decrypted_is_not_registered(
    tunnel_registry, redis_service, ngrok_environment, auth_token
):
    """Its error names the config, never the token, and the other configs still sync."""
    broken = NgrokConfigData(name="broken", org_id=1, auth_token=auth_token)
    healthy = LocalhostConfigData(name="healthy", org_id=1)
    logged: list[str] = []
    sink_id = logger.add(logged.append, format="{message}")
    try:
        await tunnel_registry.register_many(
            WebhookConfigData(ngrok_configs=[broken], localhost_configs=[healthy])
        )
    finally:
        logger.remove(sink_id)

    ngrok_environment.ngrok.connect.assert_not_called()
    assert set(await _published_tunnel_urls(redis_service)) == {healthy.unique_id}
    [error_line] = [line for line in logged if broken.unique_id in line]
    assert "could not be decrypted" in error_line
    assert all(auth_token not in line for line in logged)


def _ngrok_config(auth_token: str) -> NgrokConfigData:
    return NgrokConfigData(name="hook", org_id=1, auth_token=auth_token)


async def _sync(tunnel_registry, config: NgrokConfigData) -> None:
    await tunnel_registry.register_many(WebhookConfigData(ngrok_configs=[config]))


async def test_resealing_the_same_ngrok_token_does_not_restart_the_tunnel(
    tunnel_registry, ngrok_environment
):
    """Django seals the token afresh on every publish; only a new token is a change."""
    first = _ngrok_config(seal("same-token"))
    resealed = _ngrok_config(seal("same-token"))
    assert first.auth_token != resealed.auth_token

    await _sync(tunnel_registry, first)
    await _sync(tunnel_registry, resealed)

    assert ngrok_environment.ngrok.connect.call_count == 1


async def test_a_rotated_ngrok_token_restarts_the_tunnel_with_the_new_token(
    tunnel_registry, ngrok_environment
):
    await _sync(tunnel_registry, _ngrok_config(seal("old-token")))
    await _sync(tunnel_registry, _ngrok_config(seal("new-token")))

    assert ngrok_environment.ngrok.connect.call_count == 2
    restarted_config = ngrok_environment.ngrok.connect.call_args.kwargs["pyngrok_config"]
    assert restarted_config.auth_token == "new-token"


async def test_an_undecryptable_ngrok_token_takes_the_restart_path_and_fails_loudly(
    tunnel_registry, ngrok_environment
):
    forged_token = "gAAAAAforged-ngrok-token"
    await _sync(tunnel_registry, _ngrok_config(seal("old-token")))
    logged: list[str] = []
    sink_id = logger.add(logged.append, format="{message}")
    try:
        await _sync(tunnel_registry, _ngrok_config(forged_token))
    finally:
        logger.remove(sink_id)

    assert any("changed. Restarting" in line for line in logged)
    assert any("Error registering" in line and "could not be decrypted" in line for line in logged)
    assert all(forged_token not in line for line in logged)
    assert ngrok_environment.ngrok.connect.call_count == 1


def _localhost_config(sealed_secret: str) -> LocalhostConfigData:
    auth = WebhookTriggerAuthData(
        kind="webhook", header_name="EPICSTAFF_API_KEY", secret=sealed_secret
    )
    return LocalhostConfigData(name="hook", org_id=1, auth=auth)


async def _sync_logged(tunnel_registry, config: LocalhostConfigData) -> list[str]:
    logged: list[str] = []
    sink_id = logger.add(logged.append, format="{message}")
    try:
        await tunnel_registry.register_many(WebhookConfigData(localhost_configs=[config]))
    finally:
        logger.remove(sink_id)
    return logged


async def test_resealing_the_same_auth_secret_is_not_an_auth_update(tunnel_registry):
    """Django reseals the secret on every publish; that alone must not count as a change."""
    first = _localhost_config(seal("hook-secret"))
    await _sync_logged(tunnel_registry, first)

    logged = await _sync_logged(tunnel_registry, _localhost_config(seal("hook-secret")))

    assert not any("updated without tunnel restart" in line for line in logged)
    _, routed_config = await tunnel_registry.resolve_by_path("hook")
    assert routed_config.auth.secret == first.auth.secret


async def test_a_new_auth_secret_is_swapped_in_without_a_restart(tunnel_registry):
    await _sync_logged(tunnel_registry, _localhost_config(seal("old-secret")))
    rotated = _localhost_config(seal("new-secret"))

    logged = await _sync_logged(tunnel_registry, rotated)

    assert any("updated without tunnel restart" in line for line in logged)
    assert not any("changed. Restarting" in line for line in logged)
    _, routed_config = await tunnel_registry.resolve_by_path("hook")
    assert routed_config.auth.secret == rotated.auth.secret
    assert all("new-secret" not in line and rotated.auth.secret not in line for line in logged)
