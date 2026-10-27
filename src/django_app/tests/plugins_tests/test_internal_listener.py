"""Which plugin listener a request came through: either, the internal one, or the development one."""

import pytest
from django.test import RequestFactory
from plugins.identity.internal_listener import (
    came_through_a_plugin_listener,
    came_through_development_listener,
    came_through_internal_listener,
)

SECRET = "s" * 32
MISSING = object()


@pytest.fixture(autouse=True)
def gateway_secret(settings):
    settings.PLUGINS_GATEWAY_SECRET = SECRET


def _request(secret=SECRET, development_header=MISSING):
    headers = {}
    if secret is not None:
        headers["HTTP_X_PLUGIN_NETWORK_SECRET"] = secret
    if development_header is not MISSING:
        headers["HTTP_X_PLUGIN_DEVELOPMENT_LISTENER"] = development_header
    return RequestFactory().get("/", **headers)


def _listeners(request) -> tuple[bool, bool, bool]:
    return (
        came_through_a_plugin_listener(request),
        came_through_internal_listener(request),
        came_through_development_listener(request),
    )


def test_the_secret_without_the_development_header_is_the_internal_listener():
    assert _listeners(_request()) == (True, True, False)


def test_the_secret_with_the_development_header_is_the_development_listener():
    assert _listeners(_request(development_header="1")) == (True, False, True)


@pytest.mark.parametrize("value", ["0", "", "true"])
def test_a_development_header_with_another_value_is_neither_listener(value):
    assert _listeners(_request(development_header=value)) == (True, False, False)


@pytest.mark.parametrize("secret", [None, "", "wrong", SECRET[:-1]], ids=["missing", "empty", "wrong", "prefix"])
@pytest.mark.parametrize("development_header", [MISSING, "1"], ids=["internal", "development"])
def test_without_the_secret_no_listener_is_trusted(secret, development_header):
    assert _listeners(_request(secret=secret, development_header=development_header)) == (False, False, False)


def test_no_listener_is_trusted_while_the_secret_is_unconfigured(settings):
    settings.PLUGINS_GATEWAY_SECRET = "none"

    assert _listeners(_request(secret="none")) == (False, False, False)
