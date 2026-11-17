import importlib
from contextlib import contextmanager

import pytest
from django.test import Client, override_settings
from django.urls import Resolver404, clear_url_caches, resolve

import django_app.urls
import django_app.yasg

# Same reason as test_required_signing_keys.py: nothing here touches the database,
# but tests/conftest.py has a session-scoped autouse `flush_test_db_once` fixture
# whose flush would target the real `crew` dev database unless a test pulls in
# proper test-database setup.
pytestmark = pytest.mark.django_db

DOC_PATHS = ("/api/schema/", "/swagger/", "/redoc/")
RUN_SESSION_STREAM_DOC_PATH = "/api/run-session/subscribe/1/swagger/"
SWAGGER_TOKEN_PATH = "/api/auth/swagger-token/"
WRONG_CREDENTIALS = {"username": "nobody@example.com", "password": "wrong-password"}


def _rebuild_urlconf() -> None:
    """Re-import the URL modules so yasg's import-time DEBUG check runs again."""
    importlib.reload(django_app.yasg)
    importlib.reload(django_app.urls)
    clear_url_caches()


@contextmanager
def debug(enabled: bool):
    """Rebuild the URLconf with DEBUG set to the given value, restoring it on exit."""
    with override_settings(DEBUG=enabled):
        _rebuild_urlconf()
        yield
    _rebuild_urlconf()


@pytest.mark.parametrize("path", DOC_PATHS)
def test_doc_route_is_served_in_debug(path):
    with debug(enabled=True):
        assert Client().get(path).status_code == 200


@pytest.mark.parametrize("path", DOC_PATHS)
def test_doc_route_is_absent_outside_debug(path):
    with debug(enabled=False):
        assert Client().get(path).status_code == 404


def test_disabling_debug_leaves_the_api_reachable():
    with debug(enabled=False):
        assert Client().get("/api/schema/").status_code == 404
        assert Client().get("/api/auth/login/").status_code != 404


def test_swagger_token_endpoint_is_served_in_debug():
    with debug(enabled=True):
        response = Client().post(SWAGGER_TOKEN_PATH, data=WRONG_CREDENTIALS)
        assert response.status_code != 404


def test_swagger_token_endpoint_is_absent_outside_debug():
    with debug(enabled=False):
        response = Client().post(SWAGGER_TOKEN_PATH, data=WRONG_CREDENTIALS)
        assert response.status_code == 404


def test_run_session_stream_doc_stub_is_absent_outside_debug():
    with debug(enabled=False), pytest.raises(Resolver404):
        resolve(RUN_SESSION_STREAM_DOC_PATH)


def test_run_session_stream_doc_stub_is_mounted_in_debug():
    with debug(enabled=True):
        match = resolve(RUN_SESSION_STREAM_DOC_PATH)
        assert match.url_name == "run-session-subscribe-swagger"
