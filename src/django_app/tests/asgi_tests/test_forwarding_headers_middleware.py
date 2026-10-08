"""DropUnderscoreForwardingHeadersMiddleware around a stub ASGI app.

The end-to-end check, through the real application into a DRF throttle, is in
tests/api_tests/test_auth_throttles.py.
"""

import pytest
from asgiref.sync import async_to_sync

from django_app.forwarding_headers import DropUnderscoreForwardingHeadersMiddleware


# Sync tests on purpose: a pure-async test that runs first in a session makes the
# session fixture `flush_test_db_once` connect to the non-test database.


class RecordingApp:
    def __init__(self):
        self.scope = None

    async def __call__(self, scope, receive, send):
        self.scope = scope


def _pass_through(scope):
    downstream = RecordingApp()
    async_to_sync(DropUnderscoreForwardingHeadersMiddleware(downstream))(scope, None, None)
    return downstream.scope


def _scope(scope_type, headers):
    return {"type": scope_type, "path": "/api/auth/login/", "headers": headers}


@pytest.mark.parametrize("scope_type", ["http", "websocket"])
def test_underscore_forwarded_for_is_dropped_and_dash_one_kept(scope_type):
    scope = _scope(
        scope_type,
        [
            (b"host", b"localhost"),
            (b"x-forwarded-for", b"10.0.0.1"),
            (b"x_forwarded_for", b"10.0.0.99"),
        ],
    )

    downstream_scope = _pass_through(scope)

    assert downstream_scope["headers"] == [
        (b"host", b"localhost"),
        (b"x-forwarded-for", b"10.0.0.1"),
    ]


@pytest.mark.parametrize(
    "header_name",
    [
        b"x_forwarded_for",
        b"x-forwarded_for",
        b"x_forwarded-for",
        b"x_forwarded_proto",
        b"x-forwarded_proto",
        b"x_forwarded_host",
        b"x_forwarded-host",
        b"x_forwarded_port",
        b"x_real_ip",
        b"x-real_ip",
        b"x_real-ip",
        b"X_Forwarded_For",
        b"X-Forwarded_FOR",
    ],
)
def test_every_underscore_spelling_of_a_forwarding_header_is_dropped(header_name):
    downstream_scope = _pass_through(_scope("http", [(header_name, b"6.6.6.6")]))

    assert downstream_scope["headers"] == []


def test_unrelated_and_dash_headers_are_left_alone():
    headers = [
        (b"x_custom_header", b"kept"),
        (b"x_forwarded_for_extra", b"kept"),
        (b"x-forwarded-for", b"10.0.0.1"),
        (b"x-forwarded-proto", b"https"),
        (b"x-forwarded-host", b"example.com"),
        (b"x-forwarded-port", b"443"),
        (b"x-real-ip", b"10.0.0.1"),
    ]

    downstream_scope = _pass_through(_scope("http", list(headers)))

    assert downstream_scope["headers"] == headers


def test_original_scope_is_not_mutated():
    headers = [(b"x_forwarded_for", b"10.0.0.99")]
    scope = _scope("http", headers)

    _pass_through(scope)

    assert scope["headers"] == [(b"x_forwarded_for", b"10.0.0.99")]


def test_lifespan_scope_without_headers_passes_through():
    scope = {"type": "lifespan"}

    downstream_scope = _pass_through(scope)

    assert downstream_scope is scope
