import httpx
import pytest
from app.core.settings import settings
from app.main import create_app
from foundation.cryptographer import FernetRotatedCryptographer
from loguru import logger
from src.shared.models import LocalhostConfigData, WebhookTriggerAuthData
from transport_secrets import TRANSPORT_HKDF_INFO, seal

PREVIOUS_TRANSPORT_KEY = "webhook-tests-previous-transport-key"

AUTHENTICATION_FAILED = {
    "type": "client_error",
    "errors": [
        {
            "code": "unauthorized",
            "detail": "Webhook authentication failed",
            "attr": None,
            "context": None,
        }
    ],
}

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
    assert response.json() == AUTHENTICATION_FAILED
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
    assert response.json() == AUTHENTICATION_FAILED
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
    assert response.json() == {
        "type": "client_error",
        "errors": [
            {
                "code": "not_found",
                "detail": "No webhook registered for path 'never-registered'",
                "attr": None,
                "context": None,
            }
        ],
    }
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
    assert [error["code"] for error in response.json()["errors"]] == ["conflict"]
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
    assert response.json() == {
        "type": "server_error",
        "errors": [
            {
                "code": "service_unavailable",
                "detail": "Webhook receiver is temporarily unavailable",
                "attr": None,
                "context": None,
            }
        ],
    }


@pytest.mark.parametrize(
    ("request_options", "expected_error"),
    [
        (
            {"json": ["not", "an", "object"]},
            {
                "code": "bad_request",
                "detail": "Webhook body must be a JSON object",
                "attr": None,
                "context": None,
            },
        ),
        (
            {"content": b'{"update_id": ', "headers": {"Content-Type": "application/json"}},
            {"code": "bad_request", "detail": "Invalid JSON body", "attr": None, "context": None},
        ),
    ],
    ids=["body-not-an-object", "unparseable-body"],
)
async def test_invalid_body_is_a_400_without_echoing_it(
    client, tunnel_registry, received_events, request_options, expected_error
):
    # The body is read only after the path resolves and the caller is authenticated.
    await _register(tunnel_registry, "any-hook", auth=_auth("webhook", "secret"))
    options = dict(request_options)
    headers = {**options.pop("headers", {}), HEADER_BY_KIND["webhook"]: "secret"}
    response = await client.post("/webhooks/any-hook", headers=headers, **options)

    assert response.status_code == 400
    assert response.json() == {"type": "client_error", "errors": [expected_error]}
    assert "update_id" not in response.text
    assert await received_events() == []


async def test_unknown_route_is_a_404_in_the_error_envelope(client):
    response = await client.get("/no-such-route")

    assert response.status_code == 404
    assert response.json() == {
        "type": "client_error",
        "errors": [{"code": "not_found", "detail": "Not Found", "attr": None, "context": None}],
    }


async def test_an_unhandled_error_is_a_500_that_hides_its_text():
    app = create_app()

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret internal detail")

    # Starlette re-raises after answering, so the server logs it; the client still gets the answer.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://webhook") as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "type": "server_error",
        "errors": [
            {"code": "unknown", "detail": "Internal server error.", "attr": None, "context": None}
        ],
    }
    assert "secret internal detail" not in response.text
