import pytest
import redis.exceptions
from app.core.settings import settings
from app.services import tunnel_config_listener as tunnel_config_listener_module
from app.services.tunnel_registry import ConfigsFailedToRegisterError
from foundation.cryptographer import FernetRotatedCryptographer
from loguru import logger
from src.shared.models import (
    LocalhostConfigData,
    NgrokConfigData,
    WebhookConfigData,
    WebhookTriggerAuthData,
)
from transport_secrets import TRANSPORT_HKDF_INFO, seal

PREVIOUS_TRANSPORT_KEY = "webhook-tests-previous-transport-key"

HEADER_BY_KIND = {
    "webhook": "EPICSTAFF_API_KEY",
    "telegram": "X-Telegram-Bot-Api-Secret-Token",
}


def _auth(kind: str, secret: str) -> WebhookTriggerAuthData:
    """The auth config as Django sends it: the secret sealed for transport."""
    return WebhookTriggerAuthData(
        kind=kind,
        header_name=HEADER_BY_KIND[kind],
        secret=seal(secret),
    )


async def _register(registry, path: str, auth=None, org_id: int = 1) -> LocalhostConfigData:
    config = LocalhostConfigData(name=path, org_id=org_id, auth=auth)
    await registry.register(config)
    return config


@pytest.mark.parametrize("kind", ["webhook", "telegram"])
async def test_authenticated_webhook_is_forwarded_to_django(
    client, tunnel_registry, received_events, kind
):
    config = await _register(tunnel_registry, "telegram-trigger/bot", auth=_auth(kind, "secret"))

    response = await client.post(
        "/webhooks/telegram-trigger/bot",
        json={"update_id": 1},
        headers={HEADER_BY_KIND[kind]: "secret"},
    )

    assert response.status_code == 200
    assert response.json()["config_id"] == config.unique_id
    assert await received_events() == [
        {"path": "telegram-trigger/bot", "payload": {"update_id": 1}, "config_id": config.unique_id}
    ]


@pytest.fixture
def previous_key_sealer(monkeypatch):
    """List a previous transport key in the settings; requested before `client`, so the
    app is built with it. Returns a sealer for that key."""
    monkeypatch.setattr(settings, "SECRETS_TRANSPORT_PREVIOUS_KEYS", [PREVIOUS_TRANSPORT_KEY])
    return FernetRotatedCryptographer(PREVIOUS_TRANSPORT_KEY, hkdf_info=TRANSPORT_HKDF_INFO)


async def test_secret_sealed_under_a_previous_key_still_authenticates(
    previous_key_sealer, client, tunnel_registry, received_events
):
    auth = WebhookTriggerAuthData(
        kind="webhook",
        header_name="EPICSTAFF_API_KEY",
        secret=previous_key_sealer.encrypt("rotated-out-secret"),
    )
    await _register(tunnel_registry, "authed-hook", auth=auth)

    response = await client.post(
        "/webhooks/authed-hook", json={"a": 1}, headers={"EPICSTAFF_API_KEY": "rotated-out-secret"}
    )

    assert response.status_code == 200
    assert len(await received_events()) == 1


@pytest.mark.parametrize(
    ("secret", "headers"),
    [
        ("correct-secret", {}),
        ("correct-secret", {"EPICSTAFF_API_KEY": "wrong-secret"}),
        ("correct-secret", {"EPICSTAFF_API_KEY": ""}),
        # No auth configured must fail closed: there is no unauthenticated dispatch.
        (None, {"EPICSTAFF_API_KEY": "correct-secret"}),
    ],
    ids=["missing-header", "wrong-secret", "empty-header", "path-without-auth"],
)
async def test_unauthenticated_webhook_is_rejected_with_401(
    client, tunnel_registry, received_events, secret, headers
):
    auth = None if secret is None else _auth("webhook", secret)
    await _register(tunnel_registry, "authed-hook", auth=auth)

    response = await client.post("/webhooks/authed-hook", json={"a": 1}, headers=headers)

    assert response.status_code == 401
    assert await received_events() == []


@pytest.mark.parametrize(
    "stored_secret", ["raw-secret", "gAAAAAforged-secret"], ids=["plaintext", "forged"]
)
async def test_secret_that_cannot_be_decrypted_rejects_like_failed_auth(
    client, tunnel_registry, received_events, stored_secret
):
    """Even a token equal to the stored value is refused: only a sealed secret counts,
    and neither the value nor the token is logged."""
    auth = WebhookTriggerAuthData(
        kind="webhook", header_name="EPICSTAFF_API_KEY", secret=stored_secret
    )
    config = await _register(tunnel_registry, "authed-hook", auth=auth)
    logged: list[str] = []
    sink_id = logger.add(logged.append, format="{message}")
    try:
        response = await client.post(
            "/webhooks/authed-hook", json={"a": 1}, headers={"EPICSTAFF_API_KEY": stored_secret}
        )
    finally:
        logger.remove(sink_id)

    assert response.status_code == 401
    assert response.json() == {"detail": "Webhook authentication failed"}
    assert await received_events() == []
    assert any(config.unique_id in line and "could not be decrypted" in line for line in logged)
    assert all(stored_secret not in line for line in logged)


async def test_presenting_the_sealed_secret_itself_is_rejected(
    client, tunnel_registry, received_events
):
    auth = _auth("webhook", "correct-secret")
    await _register(tunnel_registry, "authed-hook", auth=auth)

    response = await client.post(
        "/webhooks/authed-hook", json={"a": 1}, headers={"EPICSTAFF_API_KEY": auth.secret}
    )

    assert response.status_code == 401
    assert await received_events() == []


async def test_unregistered_path_returns_404(client, received_events):
    response = await client.post("/webhooks/never-registered", json={"a": 1})

    assert response.status_code == 404
    assert await received_events() == []


async def test_path_registered_by_two_orgs_is_refused_rather_than_guessed(
    client, tunnel_registry, received_events
):
    """The request carries only the path, so routing it to either org could leak one
    org's event into the other's graph."""
    auth = _auth("webhook", "secret")
    await _register(tunnel_registry, "shared-path", auth=auth, org_id=1)
    await _register(tunnel_registry, "shared-path", auth=auth, org_id=2)

    response = await client.post(
        "/webhooks/shared-path", json={"a": 1}, headers={"EPICSTAFF_API_KEY": "secret"}
    )

    assert response.status_code == 409
    assert await received_events() == []


@pytest.mark.parametrize("requested", ["my-hook", "my-hook/"])
async def test_path_matching_ignores_surrounding_slashes(
    client, tunnel_registry, received_events, requested
):
    await _register(tunnel_registry, "/my-hook/", auth=_auth("webhook", "secret"))

    response = await client.post(
        f"/webhooks/{requested}", json={"a": 1}, headers={"EPICSTAFF_API_KEY": "secret"}
    )

    assert response.status_code == 200
    assert len(await received_events()) == 1


async def test_returns_503_when_no_received_events_receives_the_event(client, tunnel_registry):
    """Telegram only redelivers an update after a non-2xx response, so a 200 for an
    event that reached no listener would lose the chat message."""
    await _register(tunnel_registry, "telegram-trigger/bot", auth=_auth("telegram", "tg-secret"))

    response = await client.post(
        "/webhooks/telegram-trigger/bot",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"},
    )

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"


@pytest.mark.parametrize(
    "redis_error", [redis.exceptions.ConnectionError, redis.exceptions.TimeoutError]
)
async def test_returns_503_when_redis_fails_on_publish(
    client, tunnel_registry, redis_service, monkeypatch, redis_error
):
    """Redis down or past its socket timeout: the event was not handed over, so the
    sender must be asked to retry, not handed a 500."""
    await _register(tunnel_registry, "telegram-trigger/bot", auth=_auth("telegram", "tg-secret"))

    async def failing_publish(channel, message):
        raise redis_error("Redis is unreachable")

    monkeypatch.setattr(redis_service.client, "publish", failing_publish)

    response = await client.post(
        "/webhooks/telegram-trigger/bot",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"},
    )

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    # The sender is on the internet: the Redis error and channel stay in the server log.
    assert settings.WEBHOOK_MESSAGE_CHANNEL not in response.text
    assert "Redis is unreachable" not in response.text


async def test_webhook_before_the_first_config_sync_returns_503_not_404(
    unsynced_client, received_events
):
    """Before Django's configs arrive every path is unknown; a 404 would tell the sender
    the URL is wrong instead of asking it to retry."""
    response = await unsynced_client.post("/webhooks/hook", json={"a": 1})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert await received_events() == []


async def test_webhook_registered_by_the_first_config_sync_is_forwarded(
    unsynced_client, tunnel_registry, received_events
):
    auth = _auth("webhook", "secret")
    await tunnel_registry.register_many(
        WebhookConfigData(localhost_configs=[LocalhostConfigData(name="hook", org_id=1, auth=auth)])
    )

    response = await unsynced_client.post(
        "/webhooks/hook", json={"a": 1}, headers={"EPICSTAFF_API_KEY": "secret"}
    )

    assert response.status_code == 200
    assert [event["path"] for event in await received_events()] == ["hook"]


async def test_health_check_passes_until_the_config_listener_is_unsynced_too_long(client):
    response = await client.get("/")

    assert response.status_code == 200


async def test_health_check_fails_once_the_config_listener_is_unsynced_too_long(
    client, monkeypatch
):
    # The client's listener never ran, so it has been unsynced since it was created.
    monkeypatch.setattr(tunnel_config_listener_module, "UNHEALTHY_AFTER_UNSYNCED_SECONDS", 0)

    response = await client.get("/")

    assert response.status_code == 503


async def test_webhook_whose_restart_failed_answers_503_and_rejects_its_old_secret(
    client, tunnel_registry, received_events, ngrok_environment
):
    """The old tunnel is gone, so its old secret no longer gets an event through; the
    sender is asked to retry because the webhook still exists in Django."""
    hook = NgrokConfigData(
        name="hook", org_id=1, auth_token=seal("old-token"), auth=_auth("webhook", "old-secret")
    )
    await tunnel_registry.register_many(WebhookConfigData(ngrok_configs=[hook]))
    unusable_hook = hook.model_copy(
        update={"auth_token": "gAAAAAforged-ngrok-token", "auth": _auth("webhook", "new-secret")}
    )
    with pytest.raises(ConfigsFailedToRegisterError):
        await tunnel_registry.register_many(WebhookConfigData(ngrok_configs=[unusable_hook]))

    response = await client.post(
        "/webhooks/hook", json={"a": 1}, headers={"EPICSTAFF_API_KEY": "old-secret"}
    )

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert await received_events() == []
