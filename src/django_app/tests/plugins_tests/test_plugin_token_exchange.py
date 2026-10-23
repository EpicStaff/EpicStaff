"""POST /api/auth/plugin-token/: a code and its PKCE verifier for a plugin login token."""

import hashlib
import json
import re
import time

import jwt
import pytest
from django_redis import get_redis_connection
from plugins.identity.plugin_login_tokens import password_fingerprint, signing_key
from plugins.models import GrantState, PluginGrant
from plugins.throttles import PluginTokenIpThrottle
from rbac.models import OrganizationUser
from rest_framework.test import APIClient

from tests.plugins_tests.login_helpers import (
    EPICSTAFF_ORIGIN,
    TOKEN_URL,
    WEATHER_ORIGIN,
    code_for,
    exchange,
    pkce_pair,
    session_cookie,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("login_platform")]


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def grant(loginable_weather, grant_to, acme):
    return grant_to(loginable_weather, acme)


@pytest.fixture
def login(client, member_only, grant):
    """A code just issued to Acme's member, with its verifier."""
    verifier, challenge = pkce_pair()
    return code_for(client, member_only, challenge=challenge), verifier


def _assert_no_store_and_no_cookie(response):
    assert response["Cache-Control"] == "no-store"
    assert not response.cookies


def _code_key(code):
    return f"plugins:auth_code:{hashlib.sha256(code.encode()).hexdigest()}"


# ---- the happy path ----


def test_the_exchange_answers_with_a_token_and_what_it_stands_for(client, login, member_only, acme):
    code, verifier = login

    response = exchange(client, code, verifier)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "access_token": body["access_token"],
        "token_type": "Bearer",
        "expires_in": 900,
        "plugin": {"identifier": "weather", "version": "0.2.0"},
        "org": {"id": acme.pk, "name": acme.name},
        "user": {"id": member_only.pk, "email": member_only.email, "name": member_only.effective_display_name},
        "plugin_permissions": ["read"],
    }
    _assert_no_store_and_no_cookie(response)


def test_the_token_carries_the_pinned_header_and_claims(client, login, member_only, acme, grant):
    code, verifier = login

    token = exchange(client, code, verifier).json()["access_token"]

    assert jwt.get_unverified_header(token) == {"alg": "HS256", "typ": "epicstaff-plugin-login+jwt"}
    claims = jwt.decode(token, signing_key(), algorithms=["HS256"], audience=WEATHER_ORIGIN, issuer=EPICSTAFF_ORIGIN)
    assert claims == {
        "token_type": "plugin_login",
        "iss": EPICSTAFF_ORIGIN,
        "aud": WEATHER_ORIGIN,
        "sub": str(member_only.pk),
        "org": acme.pk,
        "plugin": "weather",
        "grant": grant.pk,
        "pwd": password_fingerprint(member_only.password),
        "iat": claims["iat"],
        "exp": claims["iat"] + 900,
        "jti": claims["jti"],
    }
    assert re.fullmatch(r"[0-9a-f]{32}", claims["jti"])
    assert abs(claims["iat"] - time.time()) < 60
    for never in ("is_superadmin", "refresh", "scopes", "hash_password"):
        assert never not in claims


def test_another_user_s_session_cookie_on_the_request_is_ignored(client, login, member_only, admin_acme):
    code, verifier = login

    response = exchange(client, code, verifier, HTTP_COOKIE=session_cookie(admin_acme))

    assert response.status_code == 200
    assert response.json()["user"]["id"] == member_only.pk


# ---- codes are single-use and bound to the verifier and origin ----


def test_a_wrong_verifier_burns_the_code(client, login):
    code, verifier = login

    wrong = exchange(client, code, pkce_pair()[0])
    right_afterwards = exchange(client, code, verifier)

    assert (wrong.status_code, wrong.json()["code"]) == (400, "invalid_grant")
    assert (right_afterwards.status_code, right_afterwards.json()["code"]) == (400, "invalid_grant")


def test_a_code_works_once(client, login):
    code, verifier = login

    assert exchange(client, code, verifier).status_code == 200
    again = exchange(client, code, verifier)

    assert (again.status_code, again.json()["code"]) == (400, "invalid_grant")


def test_an_expired_code_is_refused(client, login):
    code, verifier = login
    get_redis_connection("default").pexpire(_code_key(code), 1)
    time.sleep(0.05)

    response = exchange(client, code, verifier)

    assert (response.status_code, response.json()["code"]) == (400, "invalid_grant")


def test_a_password_change_after_the_code_was_issued_burns_it(client, login, member_only):
    code, verifier = login
    member_only.set_password("ChangedPass789!")
    member_only.save(update_fields=["password"])

    response = exchange(client, code, verifier)

    assert (response.status_code, response.json()["code"]) == (400, "invalid_grant")
    assert not get_redis_connection("default").exists(_code_key(code))
    assert exchange(client, code, verifier).json()["code"] == "invalid_grant"


def test_an_unknown_code_is_refused(client, grant):
    response = exchange(client, "c" * 43, pkce_pair()[0])

    assert (response.status_code, response.json()["code"]) == (400, "invalid_grant")
    _assert_no_store_and_no_cookie(response)


@pytest.mark.parametrize(
    "origin",
    ["http://other.plugins.epicstaff.localhost", EPICSTAFF_ORIGIN, None],
    ids=["another-plugin", "epicstaff", "absent"],
)
def test_the_exchange_must_come_from_the_plugin_s_own_origin(client, login, origin):
    code, verifier = login

    response = exchange(client, code, verifier, origin=origin)

    assert (response.status_code, response.json()["code"]) == (400, "invalid_grant")
    assert exchange(client, code, verifier).status_code == 400


# ---- JSON only, checked before the code is touched ----


@pytest.mark.parametrize("body", ["code=x", ""], ids=["with-a-body", "empty-body"])
def test_text_plain_is_refused_before_the_code_is_touched(client, login, body):
    code, verifier = login

    response = client.post(TOKEN_URL, body, content_type="text/plain", HTTP_ORIGIN=WEATHER_ORIGIN)

    assert (response.status_code, response.json()["code"]) == (415, "unsupported_media_type")
    _assert_no_store_and_no_cookie(response)
    assert exchange(client, code, verifier).status_code == 200


@pytest.mark.parametrize("content_type", ["application/json; charset=utf-8", "Application/JSON"])
def test_json_with_parameters_or_in_any_case_is_accepted(client, login, content_type):
    code, verifier = login

    response = client.post(
        TOKEN_URL,
        f'{{"code": "{code}", "code_verifier": "{verifier}"}}',
        content_type=content_type,
        HTTP_ORIGIN=WEATHER_ORIGIN,
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("build_body", "locs"),
    [
        (lambda code, verifier: json.dumps({"code_verifier": verifier}), ["code"]),
        (lambda code, verifier: json.dumps({"code": code}), ["code_verifier"]),
        (lambda code, verifier: json.dumps({"code": code, "code_verifier": verifier, "redirect_uri": "x"}), ["redirect_uri"]),
        (lambda code, verifier: json.dumps({"code": 42, "code_verifier": verifier}), ["code"]),
        (lambda code, verifier: json.dumps({"code": code, "code_verifier": "short"}), ["code_verifier"]),
        (lambda code, verifier: json.dumps([code, verifier]), ["body"]),
        (lambda code, verifier: '{"code": "' + code, ["body"]),
        (lambda code, verifier: "", ["code", "code_verifier"]),
    ],
    ids=["no-code", "no-verifier", "unknown-key", "code-not-a-string", "short-verifier", "array", "malformed-json", "empty"],
)
def test_a_body_of_the_wrong_shape_is_refused_without_echoing_it_and_leaves_the_code(client, login, build_body, locs):
    code, verifier = login

    response = client.post(
        TOKEN_URL, build_body(code, verifier), content_type="application/json", HTTP_ORIGIN=WEATHER_ORIGIN
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid"
    assert sorted(error["loc"] for error in response.json()["errors"]) == locs
    assert code not in response.content.decode()
    assert verifier not in response.content.decode()
    assert exchange(client, code, verifier).status_code == 200


# ---- access is resolved again at the exchange ----


def _remove_membership(user, organization, grant):
    OrganizationUser.objects.filter(user=user, org=organization).delete()


def _suspend_grant(user, organization, grant):
    PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.SUSPENDED)


def _recreate_grant(user, organization, grant):
    plugin = grant.plugin
    PluginGrant.objects.filter(pk=grant.pk).delete()
    PluginGrant.objects.create(plugin=plugin, org=organization, state=GrantState.ACTIVE, created_by=grant.created_by)


def _deactivate_organization(user, organization, grant):
    organization.is_active = False
    organization.save(update_fields=["is_active"])


def _deactivate_user(user, organization, grant):
    user.is_active = False
    user.save(update_fields=["is_active"])


def _delete_user(user, organization, grant):
    user.delete()


@pytest.mark.parametrize(
    "lose_access",
    [_remove_membership, _suspend_grant, _recreate_grant, _deactivate_organization, _deactivate_user, _delete_user],
    ids=["membership-removed", "grant-suspended", "grant-recreated", "organization-inactive", "user-inactive", "user-deleted"],
)
def test_access_lost_before_the_exchange_is_refused(client, login, member_only, acme, grant, lose_access):
    code, verifier = login
    lose_access(member_only, acme, grant)

    response = exchange(client, code, verifier)

    assert (response.status_code, response.json()["code"]) == (403, "plugin_access_denied")
    _assert_no_store_and_no_cookie(response)


def test_a_role_without_view_is_refused_at_the_exchange(client, login, member_only, acme, role_viewer):
    code, verifier = login
    OrganizationUser.objects.filter(user=member_only, org=acme).update(role=role_viewer)

    assert exchange(client, code, verifier).status_code == 403


# ---- CORS: only the plugin's origin, never with credentials ----


def test_the_preflight_from_the_plugin_origin_is_answered_without_credentials(client, grant):
    response = client.options(
        TOKEN_URL,
        HTTP_ORIGIN=WEATHER_ORIGIN,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
    )

    assert response.status_code == 204
    assert response["Access-Control-Allow-Origin"] == WEATHER_ORIGIN
    assert response["Access-Control-Allow-Methods"] == "POST"
    assert response["Access-Control-Allow-Headers"] == "content-type"
    assert response["Access-Control-Max-Age"] == "600"
    assert "origin" in response["Vary"].lower()
    assert "Access-Control-Allow-Credentials" not in response.headers


@pytest.mark.parametrize("status_code", [200, 400], ids=["success", "error"])
def test_the_exchange_response_allows_the_plugin_origin_without_credentials(client, login, status_code):
    code, verifier = login

    response = exchange(client, code, verifier if status_code == 200 else pkce_pair()[0])

    assert response.status_code == status_code
    assert response["Access-Control-Allow-Origin"] == WEATHER_ORIGIN
    assert "origin" in response["Vary"].lower()
    assert "Access-Control-Allow-Credentials" not in response.headers


def test_a_plugin_origin_forced_into_the_cors_list_still_gets_no_credentials(client, login, settings):
    settings.CORS_ALLOWED_ORIGINS = [*(settings.CORS_ALLOWED_ORIGINS or []), WEATHER_ORIGIN]
    code, verifier = login

    response = exchange(client, code, verifier)

    assert response["Access-Control-Allow-Origin"] == WEATHER_ORIGIN
    assert "Access-Control-Allow-Credentials" not in response.headers


# ---- throttle ----


def test_the_exchange_is_throttled_per_client_address(client, grant, monkeypatch):
    assert PluginTokenIpThrottle.rate == "120/min"
    monkeypatch.setattr(PluginTokenIpThrottle, "rate", "2/min")

    statuses = [
        client.post(TOKEN_URL, "", content_type="text/plain", HTTP_ORIGIN=WEATHER_ORIGIN).status_code
        for _ in range(3)
    ]
    response = client.post(TOKEN_URL, "", content_type="text/plain", HTTP_ORIGIN=WEATHER_ORIGIN)

    assert statuses == [415, 415, 429]
    assert (response.status_code, response.json()["code"]) == (429, "throttled")
    assert "Retry-After" in response.headers
    _assert_no_store_and_no_cookie(response)
