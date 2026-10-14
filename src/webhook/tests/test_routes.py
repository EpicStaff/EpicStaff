import pytest
from src.shared.models import LocalhostConfigData, WebhookTriggerAuthData

HEADER_BY_KIND = {
    "webhook": "EPICSTAFF_API_KEY",
    "telegram": "X-Telegram-Bot-Api-Secret-Token",
}


def _auth(kind: str, secret: str) -> WebhookTriggerAuthData:
    return WebhookTriggerAuthData(kind=kind, header_name=HEADER_BY_KIND[kind], secret=secret)


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


@pytest.mark.parametrize(
    ("auth", "headers"),
    [
        (_auth("webhook", "correct-secret"), {}),
        (_auth("webhook", "correct-secret"), {"EPICSTAFF_API_KEY": "wrong-secret"}),
        (_auth("webhook", "correct-secret"), {"EPICSTAFF_API_KEY": ""}),
        # No auth configured must fail closed: there is no unauthenticated dispatch.
        (None, {"EPICSTAFF_API_KEY": "correct-secret"}),
    ],
    ids=["missing-header", "wrong-secret", "empty-header", "path-without-auth"],
)
async def test_unauthenticated_webhook_is_rejected_with_401(
    client, tunnel_registry, received_events, auth, headers
):
    await _register(tunnel_registry, "authed-hook", auth=auth)

    response = await client.post("/webhooks/authed-hook", json={"a": 1}, headers=headers)

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
