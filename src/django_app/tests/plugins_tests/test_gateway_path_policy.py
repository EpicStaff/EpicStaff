"""Canonical paths and public-path matching: the gateway decides on the canonical path only."""

import pytest
from epicstaff_plugin.contracts.manifest import PublicPath
from plugins.gateway.path_policy import canonical_path, match_public_path

from tests.plugins_tests.conftest import GATEWAY_SECRET, mark_running

CHECK_URL = "/api/plugin-gateway/check/"


def _rule(path, match="exact", methods=("GET",)):
    return PublicPath(path=path, match=match, methods=list(methods), rate_limit_per_minute=10, max_body_kb=0)


def _latin1(text: str) -> str:
    """A header value as Django sees it: the UTF-8 bytes nginx sent, read as Latin-1."""
    return text.encode("utf-8").decode("latin-1")


@pytest.mark.parametrize(
    ("raw_uri", "normalized"),
    [
        ("/api/public/../private", "/api/private"),
        ("/api/public/%2e%2e/private", "/api/private"),
        ("/api/public/%2E%2E/private", "/api/private"),
        ("/api/./ping", "/api/ping"),
        ("/api//ping", "/api/ping"),
        ("/api/%2e%2e/_epicstaff/health", "/_epicstaff/health"),
        ("/api/%255fepicstaff/health", "/api/%5fepicstaff/health"),
        ("/api/%252e%252e/private", "/api/%2e%2e/private"),
        ("/api/x/%5F%65picstaff/health", "/api/x/_epicstaff/health"),
        ("/api/_EPICSTAFF/health", "/api/_EPICSTAFF/health"),
        ("/api/ping%00", "/api/ping\x00"),
        ("/api/%FF", "/api/\xff"),
        ("api/ping", "api/ping"),
        ("/api/ping", "/api/pong"),
    ],
    ids=[
        "dot dot",
        "encoded dot dot",
        "upper-case encoded dot dot",
        "dot",
        "double slash",
        "escape into the platform paths",
        "double-encoded platform marker",
        "double-encoded dot dot",
        "encoded platform marker",
        "platform marker in another case",
        "control character",
        "not UTF-8",
        "relative",
        "raw and normalised differ",
    ],
)
def test_a_path_that_is_not_canonical_is_refused(raw_uri, normalized):
    assert canonical_path(raw_uri, normalized) is None


@pytest.mark.parametrize(
    ("raw_uri", "normalized", "expected"),
    [
        ("/api/ping", "/api/ping", "/api/ping"),
        ("/api/ping?city=Berlin&x=../y", "/api/ping", "/api/ping"),
        ("/api/forecast/caf%C3%A9", _latin1("/api/forecast/café"), "/api/forecast/café"),
        ("/api/a%20b", "/api/a b", "/api/a b"),
        ("/api/ping/", "/api/ping/", "/api/ping/"),
    ],
)
def test_a_canonical_path_is_returned_decoded(raw_uri, normalized, expected):
    assert canonical_path(raw_uri, normalized) == expected


def test_an_exact_rule_matches_only_its_path_and_methods():
    rules = [_rule("/api/ping")]

    assert match_public_path(rules, "GET", "/api/ping") == (0, rules[0])
    assert match_public_path(rules, "POST", "/api/ping") is None
    assert match_public_path(rules, "GET", "/api/ping/") is None
    assert match_public_path(rules, "GET", "/api/ping/x") is None
    assert match_public_path(rules, "GET", "/API/ping") is None


def test_a_prefix_rule_matches_whole_segments():
    rules = [_rule("/api/public", match="prefix")]

    assert match_public_path(rules, "GET", "/api/public") is not None
    assert match_public_path(rules, "GET", "/api/public/a/b") is not None
    assert match_public_path(rules, "GET", "/api/publicity") is None
    assert match_public_path(rules, "GET", "/api/private") is None


def test_a_prefix_rule_ending_in_a_slash_matches_below_it():
    rules = [_rule("/api/public/", match="prefix")]

    assert match_public_path(rules, "GET", "/api/public/x") is not None
    assert match_public_path(rules, "GET", "/api/public") is None


def test_the_first_matching_rule_wins():
    rules = [_rule("/api/hooks", match="prefix", methods=["POST"]), _rule("/api/hooks/github", methods=["POST", "GET"])]

    assert match_public_path(rules, "POST", "/api/hooks/github")[0] == 0
    assert match_public_path(rules, "GET", "/api/hooks/github")[0] == 1


@pytest.mark.django_db
@pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root", "gateway_in_request_thread")
@pytest.mark.parametrize(
    ("raw_uri", "normalized"),
    [
        ("/api/public/../ping", "/api/ping"),
        ("/api/public/%2e%2e/ping", "/api/ping"),
        ("/api/%255fepicstaff/health", "/api/%5fepicstaff/health"),
    ],
)
def test_the_check_refuses_a_non_canonical_path_even_when_it_normalises_to_a_public_one(backend_plugin, anonymous_client, settings, raw_uri, normalized):
    settings.PLUGINS_GATEWAY_SECRET = GATEWAY_SECRET
    mark_running(backend_plugin())

    response = anonymous_client.get(
        CHECK_URL,
        HTTP_X_PLUGIN_GATEWAY_SECRET=GATEWAY_SECRET,
        HTTP_X_PLUGIN_IDENTIFIER="weather",
        HTTP_X_ORIGINAL_METHOD="GET",
        HTTP_X_ORIGINAL_URI=raw_uri,
        HTTP_X_ORIGINAL_NORMALIZED_PATH=normalized,
        HTTP_X_REAL_IP="203.0.113.7",
    )

    assert response.status_code == 403
    assert response.headers["X-Plugin-Deny"] == "not_found"
    assert "X-Plugin-Context" not in response.headers
