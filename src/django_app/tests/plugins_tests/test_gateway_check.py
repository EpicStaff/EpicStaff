"""The gateway check nginx asks before forwarding to a plugin's backend, in its order of checks."""

import json

import jwt
import pytest
from django.core.cache import cache
from epicstaff_plugin.contracts.gateway_context import ContextOrganization, ContextUser
from epicstaff_plugin.gateway.context_verifier import ContextRejected, ContextVerifier
from epicstaff_plugin.runtime.runtime_config import RuntimeConfig
from plugins.gateway import public_rate_limiter
from plugins.identity.plugin_login_tokens import issue_plugin_login_token, password_fingerprint, signing_key
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.models import GrantState, Plugin, PluginGrant, PluginPlacement, PluginSigningKey, PluginState
from rbac.models import OrganizationUser
from rest_framework_simplejwt.tokens import RefreshToken

from tests.plugins_tests.conftest import GATEWAY_SECRET, mark_running
from tests.plugins_tests.package_builder import PING_PATH

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root", "gateway_in_request_thread"),
]

CHECK_URL = "/api/plugin-gateway/check/"
CLIENT_ADDRESS = "203.0.113.7"


@pytest.fixture(autouse=True)
def gateway_secret(settings):
    settings.PLUGINS_GATEWAY_SECRET = GATEWAY_SECRET


@pytest.fixture(autouse=True)
def empty_rate_counters():
    cache.delete_pattern("plugins:gateway:public-rate:*")
    yield
    cache.delete_pattern("plugins:gateway:public-rate:*")


@pytest.fixture
def weather(backend_plugin):
    return mark_running(backend_plugin())


def _check(client, uri="/api/ping", normalized=None, **headers):
    meta = {
        "HTTP_X_PLUGIN_GATEWAY_SECRET": GATEWAY_SECRET,
        "HTTP_X_PLUGIN_IDENTIFIER": "weather",
        "HTTP_X_ORIGINAL_METHOD": "GET",
        "HTTP_X_ORIGINAL_URI": uri,
        "HTTP_X_ORIGINAL_NORMALIZED_PATH": normalized if normalized is not None else uri.partition("?")[0],
        "HTTP_X_ORIGINAL_CONTENT_LENGTH": "",
        "HTTP_X_ORIGINAL_TRANSFER_ENCODING": "",
        "HTTP_X_REAL_IP": CLIENT_ADDRESS,
        **headers,
    }
    return client.get(CHECK_URL, **{name: value for name, value in meta.items() if value is not None})


def _deny(response):
    return response.status_code, response.headers.get("X-Plugin-Deny")


def _set_public_paths(plugin, public_paths):
    package = plugin.current_package
    package.manifest = {**package.manifest, "public_paths": public_paths}
    package.save(update_fields=["manifest"])


def _verifier(node_client, plugin, tmp_path):
    runtime_file = node_client.post(
        f"/api/plugin-nodes/self/placements/{plugin.placement.pk}/runtime-credentials/"
    ).json()["runtime_file"]
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(runtime_file))
    return ContextVerifier(RuntimeConfig(path), fetch_jwks=lambda url: b"")


# ---- 1. the gateway secret ----


@pytest.mark.parametrize("secret", [None, "", "wrong", GATEWAY_SECRET[:-1]])
def test_a_check_without_the_gateway_secret_is_not_found(weather, anonymous_client, secret):
    response = _check(anonymous_client, HTTP_X_PLUGIN_GATEWAY_SECRET=secret)

    assert _deny(response) == (404, None)


def test_an_unconfigured_secret_accepts_nobody(weather, anonymous_client, settings):
    settings.PLUGINS_GATEWAY_SECRET = "none"

    assert _check(anonymous_client, HTTP_X_PLUGIN_GATEWAY_SECRET="none").status_code == 404


def test_only_get_reaches_the_check(weather, anonymous_client):
    response = anonymous_client.post(CHECK_URL, HTTP_X_PLUGIN_GATEWAY_SECRET=GATEWAY_SECRET)

    assert response.status_code == 405
    assert "X-Plugin-Upstream" not in response.headers


# ---- 2. a plugin with a placed backend ----


def test_an_unknown_plugin_is_not_found(weather, anonymous_client):
    assert _deny(_check(anonymous_client, HTTP_X_PLUGIN_IDENTIFIER="nothing")) == (403, "not_found")


def test_a_plugin_without_a_backend_is_not_found(running_plugin, plugin_node, anonymous_client):
    running_plugin()

    assert _deny(_check(anonymous_client)) == (403, "not_found")


def test_a_plugin_that_is_not_placed_is_not_found(weather, anonymous_client):
    Plugin.objects.filter(pk=weather.pk).update(state=PluginState.UPLOADED)

    assert _deny(_check(anonymous_client)) == (403, "not_found")


# ---- 3. the canonical path, before availability ----


def test_a_non_canonical_path_is_refused_before_availability_is_told(weather, anonymous_client):
    Plugin.objects.filter(pk=weather.pk).update(state=PluginState.FAILED)

    response = _check(anonymous_client, uri="/api/x/../ping", normalized="/api/ping")

    assert _deny(response) == (403, "not_found")


# ---- 4. availability ----


@pytest.mark.parametrize(
    ("plugin_state", "placement_changes"),
    [
        (PluginState.PROVISIONING, {}),
        (PluginState.FAILED, {}),
        (PluginState.RUNNING, {"observed_state": "starting"}),
        (PluginState.RUNNING, {"health": "failing"}),
    ],
)
def test_a_plugin_whose_process_is_not_running_and_healthy_is_unavailable(weather, anonymous_client, plugin_state, placement_changes):
    Plugin.objects.filter(pk=weather.pk).update(state=plugin_state)
    PluginPlacement.objects.filter(plugin=weather).update(**placement_changes)

    assert _deny(_check(anonymous_client)) == (403, "unavailable")


# ---- 5. public paths ----


def test_a_public_path_is_forwarded_with_a_public_context(weather, anonymous_client, node_client, tmp_path):
    response = _check(anonymous_client)

    assert response.status_code == 200
    assert response.headers["X-Plugin-Upstream"] == "es_plugins:20001"
    assert response.headers["X-Plugin-Forward-Authorization"] == "1"
    assert "X-Plugin-Deny" not in response.headers
    context = _verifier(node_client, weather, tmp_path).verify(response.headers["X-Plugin-Context"], "GET", "/api/ping")
    assert context.mode == "public"
    assert (context.user, context.org, context.permissions) == (None, None, [])
    assert (context.aud, context.iss) == ("weather", "http://epicstaff.localhost")
    assert (context.plugin.identifier, context.plugin.version) == ("weather", "0.2.0")
    assert (context.request.method, context.request.path) == ("GET", "/api/ping")
    assert context.exp - context.iat == 60


def test_the_context_is_bound_to_the_request(weather, anonymous_client, node_client, tmp_path):
    token = _check(anonymous_client).headers["X-Plugin-Context"]
    verifier = _verifier(node_client, weather, tmp_path)

    for method, path in (("POST", "/api/ping"), ("GET", "/api/other")):
        with pytest.raises(ContextRejected) as rejected:
            verifier.verify(token, method, path)
        assert rejected.value.reason == "request_mismatch"


def test_the_context_is_signed_by_the_newest_key(weather, anonymous_client):
    rotated = PluginSigningKeyService().rotate()

    token = _check(anonymous_client).headers["X-Plugin-Context"]

    assert jwt.get_unverified_header(token) == {"alg": "EdDSA", "typ": "epicstaff-plugin-context+jwt", "kid": rotated.kid}


def test_the_query_string_is_not_part_of_the_match_or_the_context(weather, anonymous_client, node_client, tmp_path):
    response = _check(anonymous_client, uri="/api/ping?city=Berlin")

    assert response.status_code == 200
    context = _verifier(node_client, weather, tmp_path).verify(response.headers["X-Plugin-Context"], "GET", "/api/ping")
    assert context.request.path == "/api/ping"


@pytest.mark.parametrize(("method", "uri"), [("GET", "/api/whoami"), ("POST", "/api/ping"), ("GET", "/api/ping/more")])
def test_any_other_path_needs_a_login(weather, anonymous_client, method, uri):
    assert _deny(_check(anonymous_client, uri=uri, HTTP_X_ORIGINAL_METHOD=method)) == (401, "login")


# ---- 6. the body cap ----


@pytest.mark.parametrize(
    ("content_length", "transfer_encoding"),
    [("1", ""), ("abc", ""), ("", "chunked"), ("", "gzip, chunked"), ("", "Chunked")],
)
def test_a_body_over_the_cap_is_too_large(weather, anonymous_client, content_length, transfer_encoding):
    response = _check(
        anonymous_client,
        HTTP_X_ORIGINAL_CONTENT_LENGTH=content_length,
        HTTP_X_ORIGINAL_TRANSFER_ENCODING=transfer_encoding,
    )

    assert _deny(response) == (403, "too_large")


def test_a_body_within_the_cap_passes(weather, anonymous_client):
    _set_public_paths(weather, [{**PING_PATH, "methods": ["POST"], "max_body_kb": 1}])

    within = _check(anonymous_client, HTTP_X_ORIGINAL_METHOD="POST", HTTP_X_ORIGINAL_CONTENT_LENGTH="1024")
    over = _check(anonymous_client, HTTP_X_ORIGINAL_METHOD="POST", HTTP_X_ORIGINAL_CONTENT_LENGTH="1025")

    assert within.status_code == 200
    assert _deny(over) == (403, "too_large")


def test_an_empty_body_passes_a_zero_cap(weather, anonymous_client):
    assert _check(anonymous_client, HTTP_X_ORIGINAL_CONTENT_LENGTH="0").status_code == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_body_method_without_a_length_is_too_large(weather, anonymous_client, method):
    _set_public_paths(weather, [{**PING_PATH, "methods": [method], "max_body_kb": 1}])

    without_length = _check(anonymous_client, HTTP_X_ORIGINAL_METHOD=method)
    with_length = _check(anonymous_client, HTTP_X_ORIGINAL_METHOD=method, HTTP_X_ORIGINAL_CONTENT_LENGTH="0")

    assert _deny(without_length) == (403, "too_large")
    assert with_length.status_code == 200


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_a_method_without_a_body_needs_no_length(weather, anonymous_client, method):
    _set_public_paths(weather, [{**PING_PATH, "methods": [method]}])

    assert _check(anonymous_client, HTTP_X_ORIGINAL_METHOD=method).status_code == 200


# ---- 7. the rate limit ----


def test_the_rate_limit_counts_per_client_address_in_one_minute_windows(weather, anonymous_client, monkeypatch):
    _set_public_paths(weather, [{**PING_PATH, "rate_limit_per_minute": 2}])
    now = [1_800_000_000.0]
    monkeypatch.setattr(public_rate_limiter.time, "time", lambda: now[0])

    allowed = [_check(anonymous_client).status_code for _ in range(2)]
    over = _deny(_check(anonymous_client))
    other_client = _check(anonymous_client, HTTP_X_REAL_IP="198.51.100.9").status_code
    now[0] += 60
    next_window = _check(anonymous_client).status_code

    assert allowed == [200, 200]
    assert over == (403, "rate_limited")
    assert other_client == 200
    assert next_window == 200


def test_the_body_cap_is_checked_before_the_rate_limit(weather, anonymous_client):
    _set_public_paths(weather, [{**PING_PATH, "rate_limit_per_minute": 1}])

    for _ in range(3):
        assert _deny(_check(anonymous_client, HTTP_X_ORIGINAL_CONTENT_LENGTH="5")) == (403, "too_large")

    assert _check(anonymous_client).status_code == 200


# ---- caching ----


def test_a_repeated_check_reads_only_the_plugin_s_availability(weather, anonymous_client, django_assert_num_queries):
    _check(anonymous_client)

    with django_assert_num_queries(1):
        response = _check(anonymous_client)

    assert response.status_code == 200


def test_a_plugin_that_stops_is_refused_at_once(weather, anonymous_client):
    assert _check(anonymous_client).status_code == 200

    PluginPlacement.objects.filter(plugin=weather).update(observed_state="failed", health="failing")

    assert _deny(_check(anonymous_client)) == (403, "unavailable")


def test_a_plugin_that_starts_is_served_at_once(backend_plugin, anonymous_client):
    plugin = backend_plugin()
    assert _deny(_check(anonymous_client)) == (403, "unavailable")

    mark_running(plugin)

    assert _check(anonymous_client).status_code == 200


def test_without_a_signing_key_the_plugin_is_unavailable(weather, anonymous_client):
    PluginSigningKey.objects.all().delete()

    assert _deny(_check(anonymous_client)) == (403, "unavailable")


# ---- 8. a path that is not public: a plugin login token ----


@pytest.fixture
def acme_grant(weather, grant_to, acme):
    return grant_to(weather, acme)


@pytest.fixture(autouse=True)
def empty_person_cache():
    cache.delete_pattern("plugins:gw:person:*")
    yield
    cache.delete_pattern("plugins:gw:person:*")


def _login_token(user, organization, grant, identifier="weather"):
    return issue_plugin_login_token(user=user, org_id=organization.pk, grant_id=grant.pk, identifier=identifier).token


def _person_key(user, organization, grant):
    return f"plugins:gw:person:weather:{organization.pk}:{user.pk}:{grant.pk}:{password_fingerprint(user.password)}"


def _logged_in_check(client, token, uri="/api/whoami", scheme="Bearer", **headers):
    return _check(client, uri=uri, HTTP_AUTHORIZATION=f"{scheme} {token}", **headers)


def test_a_valid_login_token_is_forwarded_with_a_user_context(weather, acme_grant, member_only, acme, anonymous_client, node_client, tmp_path):
    response = _logged_in_check(anonymous_client, _login_token(member_only, acme, acme_grant))

    assert response.status_code == 200
    assert response.headers["X-Plugin-Upstream"] == "es_plugins:20001"
    assert response.headers["X-Plugin-Forward-Authorization"] == "0"
    context = _verifier(node_client, weather, tmp_path).verify(response.headers["X-Plugin-Context"], "GET", "/api/whoami")
    assert context.mode == "user"
    assert context.is_user
    assert context.org == ContextOrganization(id=acme.pk, name=acme.name)
    assert context.user == ContextUser(id=member_only.pk, email=member_only.email, name=member_only.effective_display_name)
    assert context.permissions == ["read"]
    assert (context.aud, context.iss, context.plugin.version) == ("weather", "http://epicstaff.localhost", "0.2.0")
    assert (context.request.method, context.request.path) == ("GET", "/api/whoami")


@pytest.mark.parametrize("scheme", ["bearer", "BEARER"])
def test_the_bearer_scheme_is_matched_in_any_case(weather, acme_grant, member_only, acme, anonymous_client, scheme):
    assert _logged_in_check(anonymous_client, _login_token(member_only, acme, acme_grant), scheme=scheme).status_code == 200


def _no_bearer(user, organization, grant):
    return {}


def _basic_scheme(user, organization, grant):
    return {"HTTP_AUTHORIZATION": f"Basic {_login_token(user, organization, grant)}"}


def _empty_bearer(user, organization, grant):
    return {"HTTP_AUTHORIZATION": "Bearer "}


def _epicstaff_access_token(user, organization, grant):
    return {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}


def _another_plugin_s_token(user, organization, grant):
    return {"HTTP_AUTHORIZATION": f"Bearer {_login_token(user, organization, grant, identifier='other')}"}


def _expired_token(user, organization, grant):
    claims = jwt.decode(_login_token(user, organization, grant), options={"verify_signature": False})
    claims.update(iat=claims["iat"] - 1000, exp=claims["iat"] - 100)
    token = jwt.encode(claims, signing_key(), algorithm="HS256", headers={"typ": "epicstaff-plugin-login+jwt"})
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _inactive_user(user, organization, grant):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {_login_token(user, organization, grant)}"}
    user.is_active = False
    user.save(update_fields=["is_active"])
    return headers


def _password_changed(user, organization, grant):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {_login_token(user, organization, grant)}"}
    user.set_password("ChangedPass789!")
    user.save(update_fields=["password"])
    return headers


def _deleted_user(user, organization, grant):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {_login_token(user, organization, grant)}"}
    user.delete()
    return headers


def _suspended_grant(user, organization, grant):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {_login_token(user, organization, grant)}"}
    PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.SUSPENDED)
    return headers


def _recreated_grant(user, organization, grant):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {_login_token(user, organization, grant)}"}
    PluginGrant.objects.filter(pk=grant.pk).delete()
    PluginGrant.objects.create(plugin=grant.plugin, org=organization, state=GrantState.ACTIVE, created_by=grant.created_by)
    return headers


@pytest.mark.parametrize(
    "spoil",
    [
        _no_bearer,
        _basic_scheme,
        _empty_bearer,
        _epicstaff_access_token,
        _another_plugin_s_token,
        _expired_token,
        _inactive_user,
        _password_changed,
        _deleted_user,
        _suspended_grant,
        _recreated_grant,
    ],
    ids=[
        "no-bearer",
        "basic-scheme",
        "empty-bearer",
        "epicstaff-access-token",
        "another-plugin-s-token",
        "expired",
        "inactive-user",
        "password-changed",
        "deleted-user",
        "suspended-grant",
        "recreated-grant",
    ],
)
def test_a_token_that_is_not_acceptable_needs_a_login(weather, acme_grant, member_only, acme, anonymous_client, spoil):
    response = _check(anonymous_client, uri="/api/whoami", **spoil(member_only, acme, acme_grant))

    assert _deny(response) == (401, "login")
    assert "X-Plugin-Context" not in response.headers


def _role_without_view(user, organization, role_viewer):
    OrganizationUser.objects.filter(user=user, org=organization).update(role=role_viewer)


def _membership_removed(user, organization, role_viewer):
    OrganizationUser.objects.filter(user=user, org=organization).delete()


def _organization_inactive(user, organization, role_viewer):
    organization.is_active = False
    organization.save(update_fields=["is_active"])


@pytest.mark.parametrize(
    "lose_access",
    [_role_without_view, _membership_removed, _organization_inactive],
    ids=["role-without-view", "membership-removed", "organization-inactive"],
)
def test_a_person_who_may_no_longer_use_the_plugin_is_forbidden(weather, acme_grant, member_only, acme, role_viewer, anonymous_client, lose_access):
    token = _login_token(member_only, acme, acme_grant)
    lose_access(member_only, acme, role_viewer)

    assert _deny(_logged_in_check(anonymous_client, token)) == (403, "forbidden")


def test_a_change_takes_effect_once_the_ten_second_window_ends(weather, acme_grant, member_only, acme, anonymous_client):
    token = _login_token(member_only, acme, acme_grant)
    assert _logged_in_check(anonymous_client, token).status_code == 200
    key = _person_key(member_only, acme, acme_grant)
    assert 0 < cache.ttl(key) <= 10

    OrganizationUser.objects.filter(user=member_only, org=acme).delete()
    within_window = _logged_in_check(anonymous_client, token)
    cache.delete(key)
    after_window = _logged_in_check(anonymous_client, token)

    assert within_window.status_code == 200
    assert _deny(after_window) == (403, "forbidden")


def test_a_token_renewed_right_after_a_password_change_is_not_refused_by_the_old_entry(
    weather, acme_grant, member_only, acme, anonymous_client
):
    old_token = _login_token(member_only, acme, acme_grant)
    assert _logged_in_check(anonymous_client, old_token).status_code == 200
    old_key = _person_key(member_only, acme, acme_grant)
    member_only.set_password("ChangedPass789!")
    member_only.save(update_fields=["password"])

    renewed = _logged_in_check(anonymous_client, _login_token(member_only, acme, acme_grant))
    cache.delete(old_key)
    old_after_window = _logged_in_check(anonymous_client, old_token)

    assert renewed.status_code == 200
    assert _deny(old_after_window) == (401, "login")


def test_the_token_itself_is_checked_on_every_request_even_with_the_person_cached(weather, acme_grant, member_only, acme, anonymous_client):
    assert _logged_in_check(anonymous_client, _login_token(member_only, acme, acme_grant)).status_code == 200

    expired = _expired_token(member_only, acme, acme_grant)

    assert _deny(_check(anonymous_client, uri="/api/whoami", **expired)) == (401, "login")


def test_a_repeated_logged_in_check_reads_only_the_plugin_s_availability(weather, acme_grant, member_only, acme, anonymous_client, django_assert_num_queries):
    token = _login_token(member_only, acme, acme_grant)
    _logged_in_check(anonymous_client, token)

    with django_assert_num_queries(1):
        response = _logged_in_check(anonymous_client, token)

    assert response.status_code == 200


def test_the_cache_keeps_no_password_hash(weather, acme_grant, member_only, acme, anonymous_client):
    _logged_in_check(anonymous_client, _login_token(member_only, acme, acme_grant))

    cached = cache.get(_person_key(member_only, acme, acme_grant))

    assert member_only.password not in str(cached)
    assert cached["password_fingerprint"] == password_fingerprint(member_only.password)


# ---- a login token on a public path never reaches the plugin ----


def test_a_public_path_with_a_plugin_login_token_stays_public_and_keeps_the_token(weather, acme_grant, member_only, acme, anonymous_client, node_client, tmp_path):
    response = _logged_in_check(anonymous_client, _login_token(member_only, acme, acme_grant), uri="/api/ping")

    assert response.status_code == 200
    assert response.headers["X-Plugin-Forward-Authorization"] == "0"
    context = _verifier(node_client, weather, tmp_path).verify(response.headers["X-Plugin-Context"], "GET", "/api/ping")
    assert (context.mode, context.user, context.org) == ("public", None, None)


@pytest.mark.parametrize("authorization", ["Bearer plugin-own-api-token", "Bearer a.b.c", "Token abc"])
def test_a_public_path_with_another_authorization_passes_it_on(weather, anonymous_client, authorization):
    response = _check(anonymous_client, HTTP_AUTHORIZATION=authorization)

    assert response.headers["X-Plugin-Forward-Authorization"] == "1"
