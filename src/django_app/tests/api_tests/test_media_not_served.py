"""MEDIA_ROOT holds voice recordings, so no URL serves it, not even in debug.

A recording is read through its organization's API; a static route would hand the file to
anyone who has its URL.
"""

import importlib

import pytest
from django.urls import Resolver404, clear_url_caches, resolve

import django_app.urls


@pytest.fixture
def debug_urlconf(settings):
    settings.DEBUG = True
    clear_url_caches()
    importlib.reload(django_app.urls)
    yield
    settings.DEBUG = False
    clear_url_caches()
    importlib.reload(django_app.urls)


def test_a_recording_path_resolves_to_no_view_in_debug(debug_urlconf):
    with pytest.raises(Resolver404):
        resolve("/media/recordings/2026/11/25/call_inbound.wav")
