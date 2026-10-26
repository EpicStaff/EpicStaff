"""The refresh cookie over HTTPS (`__Host-auth.refresh`, Path=/) and over plain http (`auth.refresh`).

Over HTTPS the cookie of the old name is expired by every response that writes the cookie, is
never read, and a request carrying the current name twice has no session at all.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from rbac.identity.refresh_cookie import (
    get_refresh_from_cookie,
    refresh_cookie_name,
    refresh_cookie_path,
)
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole

HOST_PREFIXED_NAME = "__Host-auth.refresh"
LEGACY_NAME = "auth.refresh"
LEGACY_PATH = "/api/auth/"
USER_PASSWORD = "UserStrongPass123!"


@pytest.fixture
def https(settings):
    settings.REFRESH_COOKIE_SECURE = True


@pytest.fixture
def plain_http(settings):
    settings.REFRESH_COOKIE_SECURE = False


@pytest.fixture
def existing_default_org(db):
    """The default organization a first setup or a user reset joins, so it creates none."""
    return Organization.objects.create(name="Organization", is_default=True)


def _assert_host_prefixed_session_cookie(response):
    cookie = response.cookies[HOST_PREFIXED_NAME]
    assert cookie.value
    assert (cookie["secure"], cookie["httponly"], cookie["samesite"]) == (True, True, "Lax")
    assert cookie["path"] == "/"
    assert cookie["domain"] == ""
    assert "Domain" not in cookie.output()


def _assert_legacy_cookie_expired(response):
    legacy = response.cookies[LEGACY_NAME]
    assert legacy.value == ""
    assert int(legacy["max-age"]) == 0
    assert legacy["path"] == LEGACY_PATH
    assert (legacy["secure"], legacy["httponly"], legacy["samesite"]) == (True, True, "Lax")


def _refresh_with_cookie_header(cookie_header: str):
    return APIClient().post(reverse("refresh"), HTTP_COOKIE=cookie_header)


def _user_of_access_token(response) -> int:
    return int(AccessToken(response.json()["access"])["user_id"])


# ---- names and paths ----


def test_https_names_the_cookie_with_the_host_prefix_on_the_root_path(https):
    assert (refresh_cookie_name(), refresh_cookie_path()) == (HOST_PREFIXED_NAME, "/")


def test_plain_http_keeps_the_old_name_and_path(plain_http):
    assert (refresh_cookie_name(), refresh_cookie_path()) == (LEGACY_NAME, LEGACY_PATH)


# ---- every response that starts a session, over HTTPS ----


@pytest.mark.django_db
def test_login_sets_the_host_prefixed_cookie_and_expires_the_legacy_one(https, regular_user):
    response = APIClient().post(
        reverse("login"), data={"email": regular_user.email, "password": USER_PASSWORD}, format="json"
    )

    assert response.status_code == 200
    _assert_host_prefixed_session_cookie(response)
    _assert_legacy_cookie_expired(response)


@pytest.mark.django_db
def test_first_setup_sets_the_host_prefixed_cookie_and_expires_the_legacy_one(https, existing_default_org):
    response = APIClient().post(
        reverse("first_setup"), data={"email": "first@example.com", "password": "StrongPass123!"}, format="json"
    )

    assert response.status_code == 201, response.content
    _assert_host_prefixed_session_cookie(response)
    _assert_legacy_cookie_expired(response)


@pytest.mark.django_db
def test_reset_user_sets_the_host_prefixed_cookie_and_expires_the_legacy_one(
    https, existing_default_org, superadmin_client
):
    response = superadmin_client.post(
        reverse("reset_user"), data={"email": "new-root@example.com", "password": "AnotherPass456!"}, format="json"
    )

    assert response.status_code == 201, response.content
    _assert_host_prefixed_session_cookie(response)
    _assert_legacy_cookie_expired(response)


@pytest.mark.django_db
def test_password_change_confirm_sets_the_host_prefixed_cookie_and_expires_the_legacy_one(https, db, django_user_model):
    member = django_user_model.objects.create_user(email="cookie-member@example.com", password=USER_PASSWORD)
    OrganizationUser.objects.create(
        user=member,
        org=Organization.objects.create(name="Cookie Org"),
        role=Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True),
    )
    client = APIClient()
    client.force_authenticate(user=member)
    ticket = client.post(
        reverse("profile_password_change_request"), data={"current_password": USER_PASSWORD}, format="json"
    ).json()["ticket"]

    response = client.post(
        reverse("profile_password_change_confirm"),
        data={"ticket": ticket, "new_password": "BrandNewPass456!"},
        format="json",
    )

    assert response.status_code == 200
    _assert_host_prefixed_session_cookie(response)
    _assert_legacy_cookie_expired(response)


@pytest.mark.django_db
def test_refresh_rotation_sets_the_host_prefixed_cookie_and_expires_the_legacy_one(https, regular_user):
    response = _refresh_with_cookie_header(f"{HOST_PREFIXED_NAME}={RefreshToken.for_user(regular_user)}")

    assert response.status_code == 200
    _assert_host_prefixed_session_cookie(response)
    _assert_legacy_cookie_expired(response)


# ---- the legacy cookie over HTTPS: the one-time logout ----


@pytest.mark.django_db
def test_a_legacy_cookie_alone_is_no_session(https, regular_user):
    response = _refresh_with_cookie_header(f"{LEGACY_NAME}={RefreshToken.for_user(regular_user)}")

    assert response.status_code == 401
    assert response.json() == {"detail": "No refresh token."}


@pytest.mark.django_db
def test_logout_expires_both_cookies_and_never_reads_the_legacy_one(https, regular_user, jwt_tokens):
    legacy_refresh = RefreshToken.for_user(regular_user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")

    response = client.post(reverse("logout"), HTTP_COOKIE=f"{LEGACY_NAME}={legacy_refresh}")

    assert response.status_code == 205
    assert not BlacklistedToken.objects.exists()
    assert response.cookies[HOST_PREFIXED_NAME].value == ""
    assert int(response.cookies[HOST_PREFIXED_NAME]["max-age"]) == 0
    assert response.cookies[HOST_PREFIXED_NAME]["path"] == "/"
    _assert_legacy_cookie_expired(response)


@pytest.mark.django_db
def test_legacy_and_current_cookies_together_use_the_current_one(https, regular_user, django_user_model):
    other_user = django_user_model.objects.create_user(email="legacy-owner@example.com", password=USER_PASSWORD)
    header = f"{LEGACY_NAME}={RefreshToken.for_user(other_user)}; {HOST_PREFIXED_NAME}={RefreshToken.for_user(regular_user)}"

    response = _refresh_with_cookie_header(header)

    assert response.status_code == 200
    assert _user_of_access_token(response) == regular_user.pk


# ---- a duplicated current name is no session ----


@pytest.mark.django_db
def test_a_duplicated_current_cookie_is_no_session_on_refresh(https, regular_user):
    header = f"{HOST_PREFIXED_NAME}={RefreshToken.for_user(regular_user)}; {HOST_PREFIXED_NAME}={RefreshToken.for_user(regular_user)}"

    assert _refresh_with_cookie_header(header).status_code == 401


@pytest.mark.django_db
def test_logout_with_a_duplicated_current_cookie_blacklists_nothing_and_clears(https, regular_user, jwt_tokens):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")
    header = f"{HOST_PREFIXED_NAME}={jwt_tokens['refresh']}; {HOST_PREFIXED_NAME}={RefreshToken.for_user(regular_user)}"

    response = client.post(reverse("logout"), HTTP_COOKIE=header)

    assert response.status_code == 205
    assert not BlacklistedToken.objects.exists()
    assert response.cookies[HOST_PREFIXED_NAME].value == ""
    _assert_legacy_cookie_expired(response)


@pytest.mark.django_db
@pytest.mark.parametrize("planted_first", [True, False], ids=["planted-first", "planted-last"])
def test_a_nameless_cookie_that_looks_like_the_session_cookie_leaves_no_session(https, regular_user, planted_first):
    # A cookie with an empty name and the value `__Host-auth.refresh=x` reaches the server as
    # this very chunk, which no parser can tell from the genuine cookie.
    planted = f"{HOST_PREFIXED_NAME}=x"
    genuine = f"{HOST_PREFIXED_NAME}={RefreshToken.for_user(regular_user)}"
    header = f"{planted}; {genuine}" if planted_first else f"{genuine}; {planted}"

    assert _refresh_with_cookie_header(header).status_code == 401


# ---- plain http ----


@pytest.mark.django_db
def test_plain_http_login_sets_the_old_cookie_only(plain_http, regular_user):
    response = APIClient().post(
        reverse("login"), data={"email": regular_user.email, "password": USER_PASSWORD}, format="json"
    )

    assert response.status_code == 200
    assert list(response.cookies) == [LEGACY_NAME]
    cookie = response.cookies[LEGACY_NAME]
    assert cookie.value
    assert (cookie["secure"], cookie["httponly"], cookie["samesite"]) == ("", True, "Lax")
    assert (cookie["path"], cookie["domain"]) == (LEGACY_PATH, "")


@pytest.mark.django_db
def test_plain_http_duplicated_cookie_is_no_session(plain_http, regular_user):
    header = f"{LEGACY_NAME}={RefreshToken.for_user(regular_user)}; {LEGACY_NAME}={RefreshToken.for_user(regular_user)}"

    assert _refresh_with_cookie_header(header).status_code == 401


@pytest.mark.django_db
def test_plain_http_never_reads_the_host_prefixed_name(plain_http, regular_user):
    assert _refresh_with_cookie_header(f"{HOST_PREFIXED_NAME}={RefreshToken.for_user(regular_user)}").status_code == 401


# ---- parsing the Cookie header ----


@pytest.mark.parametrize(
    ("cookie_header", "expected"),
    [
        (f"{HOST_PREFIXED_NAME}=abc", "abc"),
        (f"theme=dark;  {HOST_PREFIXED_NAME} = abc ; lang=en", "abc"),
        (f'{HOST_PREFIXED_NAME}="abc"', "abc"),
        (f"{HOST_PREFIXED_NAME}=a=b", "a=b"),
        (f"{HOST_PREFIXED_NAME}; {HOST_PREFIXED_NAME}=abc", "abc"),
        (f"{HOST_PREFIXED_NAME}=", None),
        (f"{HOST_PREFIXED_NAME}=abc; {HOST_PREFIXED_NAME}=", None),
        (f"{HOST_PREFIXED_NAME}=abc; {HOST_PREFIXED_NAME}=abc", None),
        (f"{LEGACY_NAME}=abc", None),
        ("", None),
    ],
    ids=[
        "alone",
        "among-others-with-spaces",
        "quoted",
        "value-with-equals",
        "chunk-without-equals-has-no-name",
        "empty",
        "second-one-empty",
        "same-value-twice",
        "legacy-name",
        "no-cookie-header",
    ],
)
def test_the_cookie_counts_only_when_its_name_appears_once_with_a_value(https, cookie_header, expected):
    request = APIRequestFactory().post("/api/auth/refresh/", HTTP_COOKIE=cookie_header)

    assert get_refresh_from_cookie(request) == expected
