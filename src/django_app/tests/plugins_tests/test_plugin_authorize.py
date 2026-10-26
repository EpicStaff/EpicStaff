"""GET /api/auth/plugin-authorize/: EpicStaff's half of a plugin login, answered with a redirect."""

import hashlib
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.urls import resolve
from django.utils import timezone
from django_redis import get_redis_connection
from plugins.identity import login_protocol
from plugins.identity.plugin_login_tokens import password_fingerprint
from plugins.models import GrantState, Plugin, PluginState
from plugins.views.login import PluginAuthorizeView, PluginTokenView
from plugins.views.login_organizations import PluginLoginOrganizationsView
from rbac.models import OrganizationUser
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from tests.plugins_tests.conftest import mark_running, reload_root_urlconf
from tests.plugins_tests.login_helpers import (
    CALLBACK_URL,
    EPICSTAFF_ORIGIN,
    SILENT_CALLBACK_URL,
    STATE,
    WEATHER_ORIGIN,
    authorize,
    exchange,
    pkce_pair,
    query_of,
    redirect_parts,
    session_cookie,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("login_platform")]

LOGIN_PROTOCOL_JSON = Path(__file__).resolve().parents[4] / "plugin-sdk" / "contracts" / "login-protocol.json"
EDITABLE_PERMISSIONS = [
    {"action": "read", "description": "Open it.", "defaults": {"org_admin": True, "member": True, "viewer": True}},
    {"action": "update", "description": "Edit places.", "defaults": {"org_admin": True, "member": True, "viewer": False}},
    {"action": "delete", "description": "Change settings.", "defaults": {"org_admin": True, "member": False, "viewer": False}},
]


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def weather_in_acme(loginable_weather, grant_to, acme):
    grant_to(loginable_weather, acme)
    return loginable_weather


def _assert_no_store_and_no_cookie(response):
    assert response["Cache-Control"] == "no-store"
    assert not response.cookies
    assert "Set-Cookie" not in response.headers


def _assert_callback_error(response, error, callback=CALLBACK_URL):
    assert response.status_code == 302
    target, result = redirect_parts(response)
    assert target == callback
    assert result == {"error": error, "state": STATE}


def _continue_of(response, page):
    location = response["Location"]
    assert location.startswith(f"{EPICSTAFF_ORIGIN}{page}?")
    query = query_of(location)
    assert list(query) == ["continue"]
    return query["continue"][0]


# ---- a session: a code at the plugin's own callback ----


def test_a_session_gets_a_code_at_the_plugin_s_callback_only(client, member_only, weather_in_acme):
    response = authorize(client, cookie=session_cookie(member_only))

    assert response.status_code == 302
    target, result = redirect_parts(response)
    assert target == CALLBACK_URL
    assert set(result) == {"code", "state"}
    assert result["state"] == STATE
    assert re.fullmatch(login_protocol.CODE_PATTERN, result["code"])
    _assert_no_store_and_no_cookie(response)


def test_a_silent_request_answers_at_the_silent_callback(client, member_only, weather_in_acme):
    response = authorize(client, cookie=session_cookie(member_only), prompt="none")

    target, result = redirect_parts(response)
    assert target == SILENT_CALLBACK_URL
    assert set(result) == {"code", "state"}


def test_the_session_is_only_read_never_rotated_or_blacklisted(client, member_only, weather_in_acme):
    refresh = str(RefreshToken.for_user(member_only))

    assert authorize(client, cookie=f"auth.refresh={refresh}").status_code == 302

    assert not BlacklistedToken.objects.exists()
    assert APIClient().post("/api/auth/refresh/", HTTP_COOKIE=f"auth.refresh={refresh}").status_code == 200


def test_the_code_record_binds_the_login_and_redis_holds_only_its_digest(client, member_only, acme, loginable_weather, grant_to):
    grant = grant_to(loginable_weather, acme)
    verifier, challenge = pkce_pair()

    _, result = redirect_parts(authorize(client, cookie=session_cookie(member_only), challenge=challenge))

    connection = get_redis_connection("default")
    keys = [key.decode() for key in connection.keys("plugins:auth_code:*")]
    assert keys == [f"plugins:auth_code:{hashlib.sha256(result['code'].encode()).hexdigest()}"]
    assert result["code"] not in keys[0]
    record = json.loads(connection.get(keys[0]))
    assert record == {
        "user_id": member_only.pk,
        "org_id": acme.pk,
        "grant_id": grant.pk,
        "plugin": "weather",
        "code_challenge": challenge,
        "origin": WEATHER_ORIGIN,
        "password_fingerprint": password_fingerprint(member_only.password),
        "issued_at": record["issued_at"],
    }
    assert 0 < connection.ttl(keys[0]) <= 60
    stored = connection.get(keys[0]).decode()
    assert verifier not in stored
    assert member_only.password not in stored


# ---- no session ----


@pytest.mark.parametrize("org", [None, "7"])
def test_without_a_session_the_browser_goes_to_epicstaff_s_login_with_the_rebuilt_request(client, weather_in_acme, org):
    _, challenge = pkce_pair()

    response = authorize(client, challenge=challenge, org=org)

    assert response.status_code == 302
    continue_path = _continue_of(response, "/plugin-login")
    assert re.fullmatch(login_protocol.CONTINUE_PATTERN, continue_path)
    expected = f"/api/auth/plugin-authorize/?plugin=weather&state={STATE}&code_challenge={challenge}&code_challenge_method=S256"
    assert continue_path == expected + (f"&org={org}" if org else "")
    _assert_no_store_and_no_cookie(response)


def test_without_a_session_a_silent_request_gets_login_required(client, weather_in_acme):
    _assert_callback_error(authorize(client, prompt="none"), "login_required", SILENT_CALLBACK_URL)


def _blacklisted(user):
    token = RefreshToken.for_user(user)
    token.blacklist()
    return f"auth.refresh={token}"


def _expired(user):
    token = RefreshToken.for_user(user)
    token.set_exp(from_time=timezone.now() - timedelta(days=30), lifetime=timedelta(seconds=1))
    return f"auth.refresh={token}"


def _inactive_user(user):
    cookie = session_cookie(user)
    user.is_active = False
    user.save(update_fields=["is_active"])
    return cookie


def _password_changed(user):
    cookie = session_cookie(user)
    user.set_password("ChangedPass789!")
    user.save(update_fields=["password"])
    return cookie


def _duplicated(user):
    return f"{session_cookie(user)}; {session_cookie(user)}"


def _access_token(user):
    return f"auth.refresh={RefreshToken.for_user(user).access_token}"


def _host_prefixed_name_over_http(user):
    return f"__Host-auth.refresh={RefreshToken.for_user(user)}"


@pytest.mark.parametrize(
    "spoiled_session",
    [_blacklisted, _expired, _inactive_user, _password_changed, _duplicated, _access_token, _host_prefixed_name_over_http],
    ids=["blacklisted", "expired", "inactive-user", "password-changed", "duplicated-cookie", "access-token", "other-cookie-name"],
)
def test_a_session_that_signs_in_nobody_goes_to_login(client, member_only, weather_in_acme, spoiled_session):
    response = authorize(client, cookie=spoiled_session(member_only))

    _continue_of(response, "/plugin-login")


# ---- who may use the plugin where ----


def test_a_viewer_whose_role_has_no_view_is_denied(client, make_member, role_viewer, acme, weather_in_acme):
    viewer = make_member(acme, role_viewer, "viewer-login@example.com")

    _assert_callback_error(authorize(client, cookie=session_cookie(viewer)), "access_denied")


def test_a_member_of_an_organization_without_the_grant_is_denied(client, make_member, role_member, beta, weather_in_acme):
    beta_member = make_member(beta, role_member, "beta-login@example.com")

    _assert_callback_error(authorize(client, cookie=session_cookie(beta_member)), "access_denied")


def test_a_suspended_grant_denies(client, member_only, acme, loginable_weather, grant_to):
    grant_to(loginable_weather, acme, state=GrantState.SUSPENDED)

    _assert_callback_error(authorize(client, cookie=session_cookie(member_only)), "access_denied")


def test_a_superadmin_who_is_not_a_member_is_denied(client, superadmin, weather_in_acme, acme):
    _assert_callback_error(authorize(client, cookie=session_cookie(superadmin)), "access_denied")
    _assert_callback_error(authorize(client, cookie=session_cookie(superadmin), org=str(acme.pk)), "access_denied")


def test_a_hint_naming_an_organization_one_cannot_use_it_in_is_denied(client, member_only, beta, weather_in_acme):
    _assert_callback_error(authorize(client, cookie=session_cookie(member_only), org=str(beta.pk)), "access_denied")


def test_a_member_of_one_organization_naming_another_is_denied_even_where_the_plugin_is_granted(
    client, make_member, role_member, acme, beta, loginable_weather, grant_to
):
    grant_to(loginable_weather, acme)
    grant_to(loginable_weather, beta)
    beta_member = make_member(beta, role_member, "beta-cross@example.com")

    _assert_callback_error(authorize(client, cookie=session_cookie(beta_member), org=str(acme.pk)), "access_denied")


def test_a_superadmin_member_gets_their_role_s_actions_not_every_action(
    client, superadmin, role_member, acme, backend_plugin, login_platform, grant_to
):
    plugin = mark_running(backend_plugin(user_permissions=EDITABLE_PERMISSIONS))
    grant_to(plugin, acme)
    OrganizationUser.objects.create(user=superadmin, org=acme, role=role_member)
    verifier, challenge = pkce_pair()
    _, result = redirect_parts(authorize(client, cookie=session_cookie(superadmin), challenge=challenge))

    response = exchange(client, result["code"], verifier)

    assert response.status_code == 200
    assert response.json()["plugin_permissions"] == ["read", "update"]


# ---- which organization ----


@pytest.fixture
def member_of_acme_and_beta(member_only, role_member, acme, beta, loginable_weather, grant_to):
    grant_to(loginable_weather, acme)
    grant_to(loginable_weather, beta)
    OrganizationUser.objects.create(user=member_only, org=beta, role=role_member)
    return member_only


def test_with_several_organizations_the_browser_goes_to_the_chooser(client, member_of_acme_and_beta):
    _, challenge = pkce_pair()

    response = authorize(client, cookie=session_cookie(member_of_acme_and_beta), challenge=challenge)

    continue_path = _continue_of(response, "/plugin-choose-org")
    assert re.fullmatch(login_protocol.CONTINUE_PATTERN, continue_path)
    assert "org=" not in continue_path
    assert f"code_challenge={challenge}" in continue_path


def test_with_several_organizations_a_silent_request_needs_interaction(client, member_of_acme_and_beta):
    response = authorize(client, cookie=session_cookie(member_of_acme_and_beta), prompt="none")

    _assert_callback_error(response, "interaction_required", SILENT_CALLBACK_URL)


def test_with_several_organizations_a_hint_picks_one(client, member_of_acme_and_beta, beta):
    verifier, challenge = pkce_pair()
    _, result = redirect_parts(
        authorize(client, cookie=session_cookie(member_of_acme_and_beta), challenge=challenge, org=str(beta.pk))
    )

    assert exchange(client, result["code"], verifier).json()["org"] == {"id": beta.pk, "name": beta.name}


# ---- malformed requests and plugins one cannot log in to ----


@pytest.mark.parametrize(
    ("changes", "loc"),
    [
        ({"return_path": "/me"}, "return_path"),
        ({"redirect_uri": "https://evil.example"}, "redirect_uri"),
        ({"state": [STATE, STATE]}, "state"),
        ({"org": ["1", "2"]}, "org"),
        ({"plugin": None}, "plugin"),
        ({"state": None}, "state"),
        ({"code_challenge": None}, "code_challenge"),
        ({"code_challenge_method": None}, "code_challenge_method"),
        ({"plugin": "Weather"}, "plugin"),
        ({"state": "too-short"}, "state"),
        ({"state": STATE + "\n"}, "state"),
        ({"state": "s" * 129}, "state"),
        ({"code_challenge": "c" * 42}, "code_challenge"),
        ({"code_challenge": "c" * 42 + "="}, "code_challenge"),
        ({"code_challenge_method": "plain"}, "code_challenge_method"),
        ({"org": "0"}, "org"),
        ({"org": "-1"}, "org"),
        ({"org": "1.0"}, "org"),
        ({"org": " 1"}, "org"),
        ({"org": "2147483648"}, "org"),
        ({"prompt": "login"}, "prompt"),
        ({"prompt": ""}, "prompt"),
    ],
)
def test_a_malformed_request_is_refused_with_json_never_a_redirect(client, member_only, weather_in_acme, changes, loc):
    response = authorize(client, cookie=session_cookie(member_only), **changes)

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_authorize_request"
    assert [error["loc"] for error in body["errors"]] == [loc]
    assert "Location" not in response.headers
    _assert_no_store_and_no_cookie(response)


def test_every_problem_is_reported_at_once(client, weather_in_acme):
    response = authorize(client, plugin=None, state="x", redirect_uri="https://evil.example")

    assert sorted(error["loc"] for error in response.json()["errors"]) == ["plugin", "redirect_uri", "state"]


def test_the_largest_organization_id_is_accepted(client, member_only, weather_in_acme):
    _assert_callback_error(authorize(client, cookie=session_cookie(member_only), org="2147483647"), "access_denied")


@pytest.mark.parametrize("identifier", ["missing", "weather"])
def test_a_plugin_one_cannot_log_in_to_is_not_found(client, member_only, running_plugin, acme, grant_to, identifier):
    # The running Weather here has no backend: a login token would have no `/api/` to go to.
    grant_to(running_plugin(), acme)

    response = authorize(client, cookie=session_cookie(member_only), plugin=identifier)

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_not_found"
    _assert_no_store_and_no_cookie(response)


def test_a_plugin_that_is_not_running_is_not_found(client, member_only, weather_in_acme):
    Plugin.objects.filter(pk=weather_in_acme.pk).update(state=PluginState.FAILED)

    assert authorize(client, cookie=session_cookie(member_only)).status_code == 404


def test_with_the_platform_off_there_is_no_authorize_endpoint(client, member_only, weather_in_acme, settings):
    settings.PLUGINS_ENABLED = False
    reload_root_urlconf()

    assert authorize(client, cookie=session_cookie(member_only)).status_code == 404


# ---- routes and protocol constants ----


@pytest.mark.parametrize(
    ("path", "view_class"),
    [
        ("/api/auth/plugin-authorize/", PluginAuthorizeView),
        ("/api/auth/plugin-token/", PluginTokenView),
        ("/api/plugins/weather/login-organizations/", PluginLoginOrganizationsView),
    ],
)
def test_the_login_paths_resolve_to_the_plugin_views(path, view_class):
    assert resolve(path).func.view_class is view_class


def test_the_protocol_constants_equal_the_shared_login_protocol_file():
    protocol = json.loads(LOGIN_PROTOCOL_JSON.read_text(encoding="utf-8"))
    paths = protocol["paths"]

    assert protocol["protocol"] == login_protocol.PROTOCOL
    assert (paths["authorize"], paths["token"]) == (login_protocol.AUTHORIZE_PATH, login_protocol.TOKEN_PATH)
    assert (paths["callback"], paths["silent_callback"]) == (login_protocol.CALLBACK_PATH, login_protocol.SILENT_CALLBACK_PATH)
    assert (paths["login_continue"], paths["choose_org"]) == (login_protocol.LOGIN_CONTINUE_PATH, login_protocol.CHOOSE_ORG_PATH)
    assert tuple(protocol["authorize_params"]) == login_protocol.AUTHORIZE_PARAMETERS
    assert protocol["code_challenge_method"] == login_protocol.CODE_CHALLENGE_METHOD
    assert tuple(protocol["prompt_values"]) == login_protocol.PROMPT_VALUES
    assert tuple(protocol["callback_errors"]) == login_protocol.CALLBACK_ERRORS
    patterns = protocol["patterns"]
    assert patterns["state"] == login_protocol.STATE_PATTERN
    assert patterns["code"] == login_protocol.CODE_PATTERN
    assert patterns["code_challenge"] == login_protocol.CODE_CHALLENGE_PATTERN
    assert patterns["code_verifier"] == login_protocol.CODE_VERIFIER_PATTERN
    assert patterns["continue"] == login_protocol.CONTINUE_PATTERN
    assert protocol["limits"]["code_ttl_seconds"] == login_protocol.CODE_TTL_SECONDS
    assert protocol["limits"]["token_lifetime_seconds"] == login_protocol.TOKEN_LIFETIME_SECONDS


# ---- while the plugin, or the person's organization, is being upgraded ----


def test_a_plugin_stopped_for_its_upgrade_answers_temporarily_unavailable(client, member_only, weather_in_acme):
    Plugin.objects.filter(pk=weather_in_acme.pk).update(state=PluginState.MAINTENANCE)

    _assert_callback_error(authorize(client, cookie=session_cookie(member_only)), "temporarily_unavailable")


def test_an_organization_still_upgrading_answers_temporarily_unavailable(client, member_only, acme, loginable_weather, grant_to):
    grant_to(loginable_weather, acme, state=GrantState.UPGRADING)

    _assert_callback_error(authorize(client, cookie=session_cookie(member_only)), "temporarily_unavailable")
    _assert_callback_error(
        authorize(client, cookie=session_cookie(member_only), org=str(acme.pk)), "temporarily_unavailable"
    )


def test_a_silent_request_during_an_upgrade_answers_at_the_silent_callback(client, member_only, weather_in_acme):
    Plugin.objects.filter(pk=weather_in_acme.pk).update(state=PluginState.MAINTENANCE)

    _assert_callback_error(
        authorize(client, cookie=session_cookie(member_only), prompt="none"),
        "temporarily_unavailable",
        callback=SILENT_CALLBACK_URL,
    )


def test_an_organization_whose_upgrade_failed_is_denied(client, member_only, acme, loginable_weather, grant_to):
    grant_to(loginable_weather, acme, state=GrantState.UPGRADE_FAILED)

    _assert_callback_error(authorize(client, cookie=session_cookie(member_only)), "access_denied")


def test_someone_without_the_plugin_s_view_is_denied_even_during_an_upgrade(client, make_member, role_viewer, acme, weather_in_acme):
    viewer = make_member(acme, role_viewer, "viewer-during-upgrade@example.com")
    Plugin.objects.filter(pk=weather_in_acme.pk).update(state=PluginState.MAINTENANCE)

    _assert_callback_error(authorize(client, cookie=session_cookie(viewer)), "access_denied")


def test_without_a_session_an_upgrade_still_sends_the_browser_to_login(client, weather_in_acme):
    Plugin.objects.filter(pk=weather_in_acme.pk).update(state=PluginState.MAINTENANCE)

    response = authorize(client)

    assert response.status_code == 302
    assert "/plugin-login" in response["Location"]
