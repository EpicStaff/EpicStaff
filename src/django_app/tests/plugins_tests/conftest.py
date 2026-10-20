from importlib import import_module, reload

import pytest
from django.conf import settings as django_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import clear_url_caches
from epicstaff_plugin.signing import generate_secret_key
from plugins.lifecycle.installation_service import PluginInstallationService
from plugins.models import GrantState, Plugin, PluginGrant
from plugins.packages.package_store import PackageFileMissingError
from plugins.packages.spa_publisher import SpaPublisher
from rest_framework.test import APIClient

from tests.plugins_tests.package_builder import build_package, sample_manifest
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


class InMemoryPackageStore:
    """Stands in for the plugin package bucket."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def save(self, key, file):
        self.objects[key] = file.read()

    def download(self, key, destination):
        if key not in self.objects:
            raise PackageFileMissingError(key)
        destination.write(self.objects[key])

    def delete(self, key):
        self.objects.pop(key, None)


def reload_root_urlconf():
    clear_url_caches()
    reload(import_module(django_settings.ROOT_URLCONF))
    clear_url_caches()


@pytest.fixture
def plugins_enabled(settings):
    """Turn the plugin platform on and mount its routes, as at start-up with the flag set."""
    original = settings.PLUGINS_ENABLED
    settings.PLUGINS_ENABLED = True
    settings.FRONTEND_BASE_URL = "http://epicstaff.localhost"
    settings.PLUGINS_BASE_DOMAIN = "plugins.epicstaff.localhost"
    reload_root_urlconf()
    yield
    settings.PLUGINS_ENABLED = original
    reload_root_urlconf()


@pytest.fixture
def package_store(monkeypatch):
    store = InMemoryPackageStore()
    monkeypatch.setattr("plugins.lifecycle.installation_service.get_package_store", lambda: store)
    return store


@pytest.fixture
def spa_root(settings, tmp_path_factory):
    root = tmp_path_factory.mktemp("plugin-spa")
    settings.PLUGINS_SPA_ROOT = root
    return root


@pytest.fixture
def release_key():
    return generate_secret_key()


@pytest.fixture
def trusts_release_key(settings, release_key):
    settings.PLUGINS_TRUSTED_SIGNING_KEYS = [f"release:{release_key.public_key.to_text()}"]
    return release_key


@pytest.fixture
def installation(package_store, spa_root):
    return PluginInstallationService(store=package_store, publisher=SpaPublisher(spa_root))


@pytest.fixture
def anonymous_client():
    return APIClient()


def upload_file(data: bytes, name: str = "weather-0.1.0.esplugin") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data, content_type="application/octet-stream")


@pytest.fixture
def running_plugin(installation, superadmin, django_capture_on_commit_callbacks):
    """Factory → a plugin uploaded and approved through the real service, so it is running."""

    def _make(**manifest_changes):
        data = build_package(manifest=sample_manifest(**manifest_changes))
        package = installation.upload(upload_file(data), len(data), superadmin)
        with django_capture_on_commit_callbacks(execute=True):
            installation.approve(package.pk, superadmin, untrusted_acknowledged=True)
        return Plugin.objects.get(pk=package.plugin_id)

    return _make


@pytest.fixture
def grant_to(superadmin):
    """Factory → an active grant of `plugin` to `organization`."""

    def _make(plugin, organization, state=GrantState.ACTIVE):
        return PluginGrant.objects.create(plugin=plugin, org=organization, state=state, created_by=superadmin)

    return _make
