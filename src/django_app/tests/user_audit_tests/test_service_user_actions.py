"""The internal endpoint the chat service records desk changes through: presentation tests
over HTTP, through the real middleware, with only the auditor sender replaced."""

import pytest
from rest_framework import status

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

URL = "/api/internal/user-actions/"
DESK_ID = "0192f1d2-3c4b-7a5e-8f6d-1a2b3c4d5e6f"


@pytest.fixture
def system_client(api_client, env_api_key):
    raw_key, _ = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key)
    return api_client


def _body(user, org, **overrides):
    return {
        "actor_user_id": user.id,
        "org_id": org.id,
        "action": "created",
        "target_type": "desk",
        "target_id": DESK_ID,
        "target_name": "Support",
        **overrides,
    }


def _post(client, body, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        return client.post(URL, body, format="json")


def test_records_a_rename_once_under_the_members_current_email(
    system_client, admin_acme, acme, sent_events, django_capture_on_commit_callbacks
):
    admin_acme.email = "renamed-admin@example.com"
    admin_acme.save(update_fields=["email"])

    response = _post(
        system_client,
        _body(admin_acme, acme, action="renamed", target_name="Billing", previous_name="Support"),
        django_capture_on_commit_callbacks,
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    (event,) = sent_events
    assert (
        event.org_id,
        event.actor_user_id,
        event.actor_email,
        event.actor_api_key_name,
        event.action,
        event.target_type,
        event.target_id,
        event.target_name,
        event.previous_name,
        event.route,
    ) == (
        acme.id,
        admin_acme.id,
        "renamed-admin@example.com",
        None,
        "renamed",
        "desk",
        DESK_ID,
        "Billing",
        "Support",
        None,
    )


@pytest.mark.parametrize(
    "action", ["created", "updated", "deleted", "paused", "resumed", "key_rotated"]
)
def test_records_each_desk_action_without_a_previous_name(
    system_client, admin_acme, acme, sent_events, django_capture_on_commit_callbacks, action
):
    response = _post(
        system_client, _body(admin_acme, acme, action=action), django_capture_on_commit_callbacks
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    assert [(event.action, event.previous_name) for event in sent_events] == [(action, None)]


@pytest.mark.parametrize("caller", ["anonymous", "jwt-user", "user-api-key"])
def test_only_the_system_api_key_may_record(
    request, api_client, admin_acme, acme, sent_events, django_capture_on_commit_callbacks, caller
):
    if caller == "jwt-user":
        client = request.getfixturevalue("auth_client")
    elif caller == "user-api-key":
        raw_key, _ = request.getfixturevalue("user_api_key")
        api_client.credentials(HTTP_X_API_KEY=raw_key)
        client = api_client
    else:
        client = api_client

    response = _post(client, _body(admin_acme, acme), django_capture_on_commit_callbacks)

    assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
    assert sent_events == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"target_type": "flow"},
        {"action": "moved_to_recycle_bin"},
        {"action": "signed_in"},
        {"action": "copy"},
        {"target_name": ""},
        {"target_name": "x" * 256},
    ],
)
def test_refuses_what_the_chat_service_may_not_record(
    system_client, admin_acme, acme, sent_events, django_capture_on_commit_callbacks, overrides
):
    response = _post(
        system_client, _body(admin_acme, acme, **overrides), django_capture_on_commit_callbacks
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert sent_events == []


def test_a_user_from_another_org_is_not_found(
    system_client, admin_acme, beta, sent_events, django_capture_on_commit_callbacks
):
    response = _post(system_client, _body(admin_acme, beta), django_capture_on_commit_callbacks)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert sent_events == []


def test_a_superadmin_who_is_not_a_member_is_recorded_in_the_org(
    system_client, superadmin, beta, sent_events, django_capture_on_commit_callbacks
):
    response = _post(system_client, _body(superadmin, beta), django_capture_on_commit_callbacks)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    [event] = sent_events
    assert (event.org_id, event.actor_user_id, event.actor_email) == (
        beta.id,
        superadmin.id,
        superadmin.email,
    )


def test_a_superadmin_in_an_inactive_org_is_not_found(
    system_client, superadmin, beta, sent_events, django_capture_on_commit_callbacks
):
    beta.is_active = False
    beta.save(update_fields=["is_active"])

    response = _post(system_client, _body(superadmin, beta), django_capture_on_commit_callbacks)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert sent_events == []


@pytest.mark.parametrize("inactive", ["user", "org"])
def test_an_inactive_member_or_org_is_not_found(
    system_client, admin_acme, acme, sent_events, django_capture_on_commit_callbacks, inactive
):
    deactivated = admin_acme if inactive == "user" else acme
    deactivated.is_active = False
    deactivated.save(update_fields=["is_active"])

    response = _post(system_client, _body(admin_acme, acme), django_capture_on_commit_callbacks)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert sent_events == []
