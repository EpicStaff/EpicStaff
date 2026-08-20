import importlib
from contextlib import contextmanager

import pytest
from django.test import Client, override_settings
from django.urls import clear_url_caches

import django_app.urls
import django_app.yasg

# Same reason as test_required_signing_keys.py: nothing here touches the database,
# but tests/conftest.py has a session-scoped autouse `flush_test_db_once` fixture
# whose flush would target the real `crew` dev database unless a test pulls in
# proper test-database setup.
pytestmark = pytest.mark.django_db

DOC_PATHS = ("/api/schema/", "/swagger/", "/redoc/")


def _rebuild_urlconf() -> None:
    """Re-import the URL modules so yasg's import-time ENABLE_API_DOCS check runs again."""
    importlib.reload(django_app.yasg)
    importlib.reload(django_app.urls)
    clear_url_caches()


@contextmanager
def api_docs(enabled: bool):
    """Rebuild the URLconf with ENABLE_API_DOCS set to the given value, restoring it on exit."""
    with override_settings(ENABLE_API_DOCS=enabled):
        _rebuild_urlconf()
        yield
    _rebuild_urlconf()


@pytest.mark.parametrize("path", DOC_PATHS)
def test_doc_route_is_served_when_enabled(path):
    with api_docs(enabled=True):
        assert Client().get(path).status_code == 200


@pytest.mark.parametrize("path", DOC_PATHS)
def test_doc_route_is_absent_when_disabled(path):
    with api_docs(enabled=False):
        assert Client().get(path).status_code == 404


def test_disabling_docs_leaves_the_api_reachable():
    with api_docs(enabled=False):
        assert Client().get("/api/schema/").status_code == 404
        assert Client().get("/api/auth/login/").status_code != 404
