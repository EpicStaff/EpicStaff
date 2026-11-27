"""MEDIA_ROOT holds voice recordings, so no URL serves it, not even in debug.

A recording is read through its organization's API; a static route would hand the file to
anyone who has its URL.
"""

import importlib

import pytest
from django.test import override_settings
from django.urls import Resolver404, clear_url_caches, resolve

import django_app.urls


def _rebuild_urlconf() -> None:
    """Re-import the URL module so its import-time DEBUG check runs again."""
    importlib.reload(django_app.urls)
    clear_url_caches()


@pytest.fixture
def debug_urlconf():
    with override_settings(DEBUG=True):
        _rebuild_urlconf()
        yield
    _rebuild_urlconf()


def test_a_recording_path_resolves_to_no_view_in_debug(debug_urlconf):
    with pytest.raises(Resolver404):
        resolve("/media/recordings/2026/11/25/call_inbound.wav")
