"""The gateway check nginx asks before forwarding to a plugin's backend, in its order of checks."""

import json

import jwt
import pytest
from django.core.cache import cache
from epicstaff_plugin.gateway.context_verifier import ContextRejected, ContextVerifier
from epicstaff_plugin.runtime.runtime_config import RuntimeConfig
from plugins.gateway import public_rate_limiter
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.models import Plugin, PluginPlacement, PluginSigningKey, PluginState

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
