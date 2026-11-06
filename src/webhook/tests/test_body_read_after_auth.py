"""The request body is read only after the sender is authenticated.

The invariant: an unauthenticated caller -- wrong secret, missing secret, or a path
that is not registered -- must be rejected before the service reads or parses the body,
so an anonymous request can never make the service buffer and JSON-parse a large body on
its single event loop. Only a request that has already passed the path and secret checks
reaches body parsing, where a malformed or non-object JSON body is a 400.

Each unauthenticated case sends a body that is NOT valid JSON. On the old code the body
was a declared handler parameter, so the framework parsed it during request binding and
returned 422 before the auth check ever ran; these tests fail there. On the fixed code the
auth check runs first, so the same requests get 401/404 and the body is never looked at.
"""

import pytest
from src.shared.models import LocalhostConfigData, WebhookTriggerAuthData

NOT_JSON = b"this is not json at all {["


def _auth(secret: str) -> WebhookTriggerAuthData:
    return WebhookTriggerAuthData(kind="webhook", header_name="EPICSTAFF_API_KEY", secret=secret)


async def _register(registry, path: str, auth=None, org_id: int = 1) -> LocalhostConfigData:
    config = LocalhostConfigData(name=path, org_id=org_id, auth=auth)
    await registry.register(config)
    return config


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"EPICSTAFF_API_KEY": "wrong-secret"},
        {"EPICSTAFF_API_KEY": ""},
    ],
    ids=["missing-header", "wrong-secret", "empty-header"],
)
async def test_unauthenticated_request_is_rejected_before_body_is_parsed(
    client, tunnel_registry, received_events, headers
):
    await _register(tunnel_registry, "authed-hook", auth=_auth("correct-secret"))

    response = await client.post(
        "/webhooks/authed-hook",
        content=NOT_JSON,
        headers={"Content-Type": "application/json", **headers},
    )

    # 401 (auth ran first), not 422 (body parsed first on the old code).
    assert response.status_code == 401
    assert await received_events() == []


async def test_unregistered_path_is_rejected_before_body_is_parsed(client, received_events):
    response = await client.post(
        "/webhooks/never-registered",
        content=NOT_JSON,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 404
    assert await received_events() == []


async def test_path_without_auth_is_rejected_before_body_is_parsed(
    client, tunnel_registry, received_events
):
    # A path registered with no auth must fail closed, and still before the body is read.
    await _register(tunnel_registry, "no-auth-hook", auth=None)

    response = await client.post(
        "/webhooks/no-auth-hook",
        content=NOT_JSON,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401
    assert await received_events() == []


@pytest.mark.parametrize(
    "content",
    [NOT_JSON, b"\xff\xfe\xfa"],
    ids=["malformed-json", "invalid-utf8"],
)
async def test_authenticated_request_with_undecodable_body_returns_400(
    client, tunnel_registry, received_events, content
):
    # A body that is not valid JSON (malformed) or not valid UTF-8 both reach request.json()
    # only because the request is authenticated, and both must become a 400, not a 500.
    await _register(tunnel_registry, "authed-hook", auth=_auth("correct-secret"))

    response = await client.post(
        "/webhooks/authed-hook",
        content=content,
        headers={"Content-Type": "application/json", "EPICSTAFF_API_KEY": "correct-secret"},
    )

    assert response.status_code == 400
    assert await received_events() == []


@pytest.mark.parametrize("body", [[1, 2, 3], "a string", 42], ids=["array", "string", "number"])
async def test_authenticated_request_with_non_object_json_returns_400(
    client, tunnel_registry, received_events, body
):
    await _register(tunnel_registry, "authed-hook", auth=_auth("correct-secret"))

    response = await client.post(
        "/webhooks/authed-hook",
        json=body,
        headers={"EPICSTAFF_API_KEY": "correct-secret"},
    )

    assert response.status_code == 400
    assert await received_events() == []
