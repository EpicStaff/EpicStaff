"""The bootstrap chain, asserted step by step on the responses the fixtures recorded.

Login is throttled and first-setup is one-shot, so these tests read `bootstrap.steps`
instead of repeating the calls. Credentials in the recorded bodies are redacted: a present,
non-empty credential reads as `REDACTED`.
"""

import uuid

from helpers.api import REDACTED, ApiClient, assert_error
from helpers.bootstrap import EMAIL_DOMAIN, RUNNER_ROLE_PERMISSIONS, Bootstrap, new_password


def test_stack_is_ready_and_needs_first_setup(bootstrap: Bootstrap) -> None:
    assert bootstrap.steps["health"].status_code == 200
    state = bootstrap.steps["first_setup_state"]
    assert state.status_code == 200
    assert state.body == {"needs_setup": True, "setup_mode": "open"}


def test_first_setup_creates_superadmin_and_organization(bootstrap: Bootstrap) -> None:
    step = bootstrap.steps["first_setup"]
    assert step.status_code == 201
    assert step.body["user"]["id"] == bootstrap.superadmin_user_id
    assert step.body["user"]["email"].endswith(f"@{EMAIL_DOMAIN}")
    assert step.body["user"]["is_superadmin"] is True
    assert isinstance(step.body["organization"]["id"], int)
    assert step.body["organization"]["is_active"] is True
    assert step.body["access"] == REDACTED


def test_custom_role_has_the_requested_permissions(bootstrap: Bootstrap) -> None:
    step = bootstrap.steps["custom_role"]
    assert step.status_code == 201
    assert step.body["id"] == bootstrap.role_id
    assert step.body["org_id"] == bootstrap.org_id
    assert step.body["is_built_in"] is False
    granted = {
        (entry["resource_type"], action)
        for entry in step.body["permissions"]
        for action in entry["actions"]
    }
    requested = {
        (entry["resource_type"], action)
        for entry in RUNNER_ROLE_PERMISSIONS
        for action in entry["actions"]
    }
    assert granted == requested


def test_user_is_created_in_the_organization_with_the_role(bootstrap: Bootstrap) -> None:
    step = bootstrap.steps["user"]
    assert step.status_code == 201
    assert step.body["email"] == bootstrap.user_email
    assert step.body["is_superadmin"] is False
    [membership] = step.body["memberships"]
    assert membership["role"]["id"] == bootstrap.role_id
    assert membership["organization"]["id"] == bootstrap.org_id


def test_user_login_returns_an_access_token(bootstrap: Bootstrap) -> None:
    step = bootstrap.steps["user_login"]
    assert step.status_code == 200
    assert step.body["access"] == REDACTED


def test_user_creates_an_api_key(bootstrap: Bootstrap) -> None:
    step = bootstrap.steps["api_key"]
    assert step.status_code == 201
    assert step.body["name"] == "e2e"
    assert step.body["api_key"] == REDACTED
    assert bootstrap.api_key_has_expected_prefix, "the raw API key does not start with `es-`"
    assert step.body["expires_at"] is not None


def test_api_key_validates_as_the_user(bootstrap: Bootstrap) -> None:
    step = bootstrap.steps["api_key_validate"]
    assert step.status_code == 200
    assert step.body["active"] is True
    assert step.body["owner_user_id"] == bootstrap.user_id


def test_api_key_carries_the_custom_role(bootstrap: Bootstrap) -> None:
    step = bootstrap.steps["permissions_me"]
    assert step.status_code == 200
    assert step.body["org_id"] == bootstrap.org_id
    assert step.body["is_superadmin"] is False
    assert step.body["role"]["id"] == bootstrap.role_id
    for entry in RUNNER_ROLE_PERMISSIONS:
        assert sorted(step.body["permissions"][entry["resource_type"]]) == sorted(entry["actions"])


def test_first_setup_is_closed_after_use(bootstrap: Bootstrap, anonymous_client: ApiClient) -> None:
    assert bootstrap.superadmin_user_id, "the bootstrap must have consumed first-setup"
    state = anonymous_client.get("/api/auth/first-setup/").json()
    assert state["needs_setup"] is False

    second_attempt = anonymous_client.post(
        "/api/auth/first-setup/",
        json={"email": f"e2e-second-{uuid.uuid4().hex[:10]}@{EMAIL_DOMAIN}", "password": new_password()},
        expect=None,
    )
    assert_error(second_attempt, 409, "setup_already_completed")


def test_superadmin_client_logs_in_with_a_fresh_token(superadmin_client: ApiClient, org_id: int) -> None:
    permissions = superadmin_client.get("/api/permissions/me/").json()
    assert permissions["is_superadmin"] is True
    assert permissions["org_id"] == org_id
    assert permissions["permissions"] == "*"
