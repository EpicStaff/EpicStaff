"""Every JWT is bound to the password it was minted under.

A refresh token rotated by `/api/auth/refresh/` has no OutstandingToken row,
so blacklisting cannot reach it. These tests drive a session through a
rotation first, so they only pass if the password binding itself kills it.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.identity.passwords.token_repository import PasswordResetTokenRepository
from rbac.identity.refresh_cookie import REFRESH_COOKIE_NAME

ORIGINAL_PASSWORD = "UserStrongPass123!"
NEW_PASSWORD = "BrandNewPass456!"
PROFILE_URL = "/api/profile/"


def _logged_in_and_rotated(user) -> tuple[APIClient, str]:
    """Log in, rotate the refresh cookie once, return (client, rotated access)."""
    client = APIClient()
    login = client.post(
        reverse("login"),
        data={"email": user.email, "password": ORIGINAL_PASSWORD},
        format="json",
    )
    assert login.status_code == 200
    rotated = client.post(reverse("refresh"))
    assert rotated.status_code == 200
    return client, rotated.json()["access"]


def _assert_session_dead(client: APIClient, access: str) -> None:
    refresh = client.post(reverse("refresh"))
    assert refresh.status_code == 401
    assert refresh.cookies[REFRESH_COOKIE_NAME].value == ""

    bearer = APIClient()
    bearer.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert bearer.get(PROFILE_URL).status_code == 401


@pytest.mark.django_db
def test_password_reset_confirm_kills_a_rotated_session(regular_user):
    session, access = _logged_in_and_rotated(regular_user)
    _token_row, raw_token = PasswordResetTokenRepository().create_for_user(regular_user)

    reset = APIClient().post(
        reverse("password_reset_confirm"),
        data={"token": raw_token, "new_password": NEW_PASSWORD},
        format="json",
    )

    assert reset.status_code == 200
    _assert_session_dead(session, access)


@pytest.mark.django_db
def test_admin_password_reset_kills_a_rotated_session(regular_user, superadmin_user):
    session, access = _logged_in_and_rotated(regular_user)
    admin = APIClient()
    admin.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(superadmin_user).access_token}"
    )

    reset = admin.post(
        reverse("admin_password_reset"),
        data={"user_id": regular_user.id, "new_password": NEW_PASSWORD},
        format="json",
    )

    assert reset.status_code == 204
    _assert_session_dead(session, access)


@pytest.mark.django_db
def test_password_change_kills_other_sessions_and_keeps_the_fresh_pair(regular_user):
    other_session, other_access = _logged_in_and_rotated(regular_user)
    own_session, own_access = _logged_in_and_rotated(regular_user)
    own_session.credentials(HTTP_AUTHORIZATION=f"Bearer {own_access}")
    ticket = own_session.post(
        reverse("profile_password_change_request"),
        data={"current_password": ORIGINAL_PASSWORD},
        format="json",
    ).json()["ticket"]

    change = own_session.post(
        reverse("profile_password_change_confirm"),
        data={"ticket": ticket, "new_password": NEW_PASSWORD},
        format="json",
    )

    assert change.status_code == 200
    _assert_session_dead(other_session, other_access)
    fresh = APIClient()
    fresh.credentials(HTTP_AUTHORIZATION=f"Bearer {change.json()['access']}")
    assert fresh.get(PROFILE_URL).status_code == 200
    # own_session now carries the cookie set by the change response.
    own_session.credentials()
    assert own_session.post(reverse("refresh")).status_code == 200


@pytest.mark.django_db
def test_token_without_password_claim_is_rejected(regular_user):
    """Sessions minted before the binding was enabled must not survive it."""
    refresh = RefreshToken.for_user(regular_user)
    del refresh[api_settings.REVOKE_TOKEN_CLAIM]

    bearer = APIClient()
    bearer.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    assert bearer.get(PROFILE_URL).status_code == 401

    cookie_client = APIClient()
    cookie_client.cookies[REFRESH_COOKIE_NAME] = str(refresh)
    response = cookie_client.post(reverse("refresh"))
    assert response.status_code == 401
    assert response.cookies[REFRESH_COOKIE_NAME].value == ""


@pytest.mark.django_db
def test_refresh_for_a_deleted_user_is_rejected(regular_user):
    refresh = str(RefreshToken.for_user(regular_user))
    regular_user.delete()

    client = APIClient()
    client.cookies[REFRESH_COOKIE_NAME] = refresh
    assert client.post(reverse("refresh")).status_code == 401


@pytest.mark.django_db
def test_rotation_keeps_the_password_claim(regular_user):
    session, _access = _logged_in_and_rotated(regular_user)

    rotated = RefreshToken(session.cookies[REFRESH_COOKIE_NAME].value)

    assert rotated[api_settings.REVOKE_TOKEN_CLAIM]
    assert (
        rotated.access_token[api_settings.REVOKE_TOKEN_CLAIM]
        == rotated[api_settings.REVOKE_TOKEN_CLAIM]
    )


# ---- token introspection (used by the realtime service's WebSocket auth) ----


def _introspect(system_raw_key: str, token: str) -> dict:
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=system_raw_key)
    response = client.post(reverse("token_introspect"), data={"token": token}, format="json")
    assert response.status_code == 200
    return response.json()


@pytest.mark.django_db
def test_introspect_reports_a_token_from_a_previous_password_inactive(
    regular_user, env_api_key
):
    system_raw_key, _system_key = env_api_key
    access = str(RefreshToken.for_user(regular_user).access_token)
    assert _introspect(system_raw_key, access)["active"] is True

    regular_user.set_password(NEW_PASSWORD)
    regular_user.save(update_fields=["password"])

    assert _introspect(system_raw_key, access) == {"active": False}


@pytest.mark.django_db
def test_introspect_reports_a_token_without_password_claim_inactive(
    regular_user, env_api_key
):
    system_raw_key, _system_key = env_api_key
    refresh = RefreshToken.for_user(regular_user)
    del refresh[api_settings.REVOKE_TOKEN_CLAIM]

    assert _introspect(system_raw_key, str(refresh.access_token)) == {"active": False}


@pytest.mark.django_db
def test_introspect_reports_a_token_of_an_inactive_user_inactive(regular_user, env_api_key):
    system_raw_key, _system_key = env_api_key
    access = str(RefreshToken.for_user(regular_user).access_token)
    regular_user.is_active = False
    regular_user.save(update_fields=["is_active"])

    assert _introspect(system_raw_key, access) == {"active": False}


@pytest.mark.django_db
def test_introspect_reports_a_token_of_a_deleted_user_inactive(regular_user, env_api_key):
    system_raw_key, _system_key = env_api_key
    access = str(RefreshToken.for_user(regular_user).access_token)
    regular_user.delete()

    assert _introspect(system_raw_key, access) == {"active": False}


@pytest.mark.django_db
def test_introspect_reports_a_refresh_token_inactive(regular_user, env_api_key):
    system_raw_key, _system_key = env_api_key

    assert _introspect(system_raw_key, str(RefreshToken.for_user(regular_user))) == {
        "active": False
    }


@pytest.mark.django_db
def test_refresh_for_a_deactivated_user_is_rejected_and_clears_the_cookie(regular_user):
    session, _access = _logged_in_and_rotated(regular_user)
    regular_user.is_active = False
    regular_user.save(update_fields=["is_active"])

    response = session.post(reverse("refresh"))

    assert response.status_code == 401
    assert response.json() == {"detail": "Token is invalid or expired."}
    assert response.cookies[REFRESH_COOKIE_NAME].value == ""
