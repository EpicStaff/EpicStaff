"""A newer version replacing a failed upgrade's target keeps the backend and the database that
target added: its migrations may have run already, and the running version may lack both."""

import pytest
from plugins.models import PluginUpgrade

from tests.plugins_tests.conftest import mark_running, upload_file
from tests.plugins_tests.package_builder import backend_manifest, build_package, sample_files
from tests.plugins_tests.upgrade_fixtures import start_upgrade, upload, weather_manifest

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PACKAGES_URL = "/api/admin/plugins/packages/"


def _upload(client, manifest):
    data = build_package(sample_files(manifest), manifest=manifest)
    return client.post(PACKAGES_URL, {"file": upload_file(data)}, format="multipart")


def _failed(upgrade: PluginUpgrade) -> None:
    PluginUpgrade.objects.filter(pk=upgrade.pk).update(failed_at=upgrade.started_at, step="migrate", last_error="boom")


def _refused_for(response, loc: str, message: str) -> None:
    assert (response.status_code, response.json()["code"]) == (409, "plugin_upgrade_unavailable")
    assert {"loc": loc, "message": message} in response.json()["errors"]


@pytest.fixture
def frontend_only_adding_a_backend(
    running_plugin, installation, superadmin, plugin_node, plugin_database_server, django_capture_on_commit_callbacks
):
    """A frontend-only Weather 0.6.0 whose upgrade to 0.7.0, which adds a backend and a database, failed."""
    plugin = running_plugin(version="0.6.0")
    manifest = weather_manifest("0.7.0")
    upgrade = start_upgrade(
        installation, superadmin, upload(installation, superadmin, manifest, sample_files(manifest)), django_capture_on_commit_callbacks
    )
    assert upgrade.adds_backend
    _failed(upgrade)
    return plugin


@pytest.fixture
def backend_adding_a_database(
    backend_plugin, installation, superadmin, plugin_database_server, django_capture_on_commit_callbacks
):
    """Weather 0.6.0 with a backend and no database, whose upgrade to 0.7.0, which adds one, failed."""
    plugin = mark_running(backend_plugin(version="0.6.0"))
    upgrade = start_upgrade(
        installation, superadmin, upload(installation, superadmin, weather_manifest("0.7.0")), django_capture_on_commit_callbacks
    )
    _failed(upgrade)
    return plugin


def test_a_replacement_without_the_backend_the_failed_target_added_is_refused(
    frontend_only_adding_a_backend, superadmin_client
):
    manifest = weather_manifest("0.8.0")
    for key in ("backend", "public_paths", "settings", "limits", "database", "outbound_hosts"):
        manifest.pop(key, None)

    _refused_for(_upload(superadmin_client, manifest), "manifest.backend", "a new version cannot drop the backend")


def test_a_replacement_without_the_database_the_failed_target_added_is_refused(
    frontend_only_adding_a_backend, superadmin_client
):
    manifest = weather_manifest("0.8.0")
    del manifest["database"]

    _refused_for(_upload(superadmin_client, manifest), "manifest.database", "a new version cannot drop the database")


def test_a_backend_s_replacement_without_the_database_its_failed_target_added_is_refused(
    backend_adding_a_database, superadmin_client
):
    _refused_for(
        _upload(superadmin_client, backend_manifest(version="0.8.0")),
        "manifest.database",
        "a new version cannot drop the database",
    )


def test_a_replacement_that_keeps_both_is_taken_for_review(frontend_only_adding_a_backend, superadmin_client):
    assert _upload(superadmin_client, weather_manifest("0.8.0")).status_code == 201
