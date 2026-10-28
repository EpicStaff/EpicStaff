"""What a new version of an installed plugin must be, and what it may not change."""

import pytest
from epicstaff_plugin.contracts.versions import compare_versions, is_newer
from plugins.models import Plugin, PluginDatabase, PluginPackage, PluginState, ReviewState

from tests.plugins_tests.conftest import upload_file
from tests.plugins_tests.package_builder import SAMPLE_MIGRATION, SAMPLE_MIGRATION_SQL, build_package
from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    SECOND_MIGRATION,
    SECOND_MIGRATION_SQL,
    digest,
    newer,
    upgrade_of,
    version_files,
    weather,
    weather_manifest,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PACKAGES_URL = "/api/admin/plugins/packages/"


def _upload(client, manifest, files=None):
    data = build_package(files, manifest=manifest)
    return client.post(PACKAGES_URL, {"file": upload_file(data)}, format="multipart")


def test_versions_are_ordered_by_semver_precedence_through_the_sdk():
    ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-beta", "1.0.0-rc.1", "1.0.0", "1.0.1", "1.10.0"]

    assert all(compare_versions(left, right) == -1 for left, right in zip(ordered, ordered[1:]))
    assert compare_versions("0.7.0+2", "0.7.0") == 0
    assert not is_newer("0.7.0+2", "0.7.0")


@pytest.mark.parametrize("version", ["0.6.0", "0.5.9", "0.6.0+build.7", "0.6.0-rc.1"])
def test_a_version_that_is_not_newer_is_refused_naming_both_versions(weather, superadmin_client, version):
    response = _upload(superadmin_client, weather_manifest(version))

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "plugin_version_not_newer"
    assert body["message"] == f"{version} is not newer than the installed 0.6.0"
    assert (body["installed_version"], body["latest_version"]) == ("0.6.0", "0.6.0")
    assert PluginPackage.objects.filter(plugin=weather).count() == 1


def test_a_version_not_newer_than_an_open_upgrade_s_target_is_refused(weather, newer, upgrade_of, superadmin_client):
    upgrade_of(newer("0.7.0"))

    response = _upload(superadmin_client, weather_manifest("0.7.0"))

    body = response.json()
    assert (response.status_code, body["code"]) == (409, "plugin_version_not_newer")
    assert (body["installed_version"], body["latest_version"]) == ("0.6.0", "0.7.0")
    assert body["message"] == "0.7.0 is not newer than 0.7.0, the version being installed"


def test_a_newer_upload_replaces_the_pending_one(weather, newer):
    first = newer("0.7.0")
    second = newer("0.8.0")

    pending = PluginPackage.objects.filter(plugin=weather, review_state=ReviewState.PENDING)
    assert list(pending.values_list("pk", flat=True)) == [second.pk]
    assert not PluginPackage.objects.filter(pk=first.pk).exists()


def test_an_upload_keeps_the_installed_plugin_s_name_until_its_new_version_runs(weather, newer):
    newer("0.7.0", name="Weather Pro")

    assert Plugin.objects.get(pk=weather.pk).name == "Weather"


@pytest.mark.parametrize(
    ("dropped", "loc", "message"),
    [
        ("backend", "manifest.backend", "a new version cannot drop the backend"),
        ("database", "manifest.database", "a new version cannot drop the database"),
    ],
)
def test_a_new_version_cannot_drop_the_backend_or_the_database(weather, superadmin_client, dropped, loc, message):
    manifest = weather_manifest("0.7.0")
    del manifest[dropped]
    if dropped == "backend":
        for key in ("public_paths", "settings", "limits", "database", "outbound_hosts"):
            manifest.pop(key, None)

    response = _upload(superadmin_client, manifest)

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "plugin_upgrade_unavailable"
    assert {"loc": loc, "message": message} in body["errors"]


def test_a_changed_file_of_the_installed_package_is_refused(weather, superadmin_client):
    manifest = weather_manifest("0.7.0")
    files = version_files(manifest, {SAMPLE_MIGRATION: b"DROP TABLE places;\n"})

    response = _upload(superadmin_client, manifest, files)

    assert response.status_code == 409
    assert response.json()["errors"] == [
        {
            "loc": "package.database/migrations/001_places.sql",
            "message": "001_places.sql is already applied; a new version must keep it unchanged",
        }
    ]


def test_a_changed_file_that_only_the_ledger_has_is_refused(weather, superadmin_client):
    record = PluginDatabase.objects.get(plugin=weather)
    record.ledger = [*record.ledger, {"name": "002_conditions.sql", "sha256": digest(b"something else\n")}]
    record.save(update_fields=["ledger"])
    manifest = weather_manifest("0.7.0")

    response = _upload(superadmin_client, manifest, version_files(manifest, {SECOND_MIGRATION: SECOND_MIGRATION_SQL}))

    assert response.status_code == 409
    assert response.json()["errors"][0]["loc"] == "package.database/migrations/002_conditions.sql"


def test_a_migration_file_the_new_version_leaves_out_is_allowed(weather, superadmin_client):
    manifest = weather_manifest("0.7.0")
    files = version_files(manifest)
    files.pop(SAMPLE_MIGRATION)
    files["database/migrations/002_conditions.sql"] = SECOND_MIGRATION_SQL

    assert _upload(superadmin_client, manifest, files).status_code == 201


def test_the_migration_files_are_stored_at_upload_with_their_digests(weather, newer):
    package = newer("0.7.0")

    assert package.migration_files == [
        {"name": "001_places.sql", "sha256": digest(SAMPLE_MIGRATION_SQL)},
        {"name": "002_conditions.sql", "sha256": digest(SECOND_MIGRATION_SQL)},
    ]


def test_an_upload_while_the_plugin_is_uninstalled_is_refused(weather, superadmin_client):
    Plugin.objects.filter(pk=weather.pk).update(state=PluginState.UNINSTALLING)

    response = _upload(superadmin_client, weather_manifest("0.7.0"))

    assert (response.status_code, response.json()["code"]) == (409, "plugin_uninstalling")


def test_an_upload_during_maintenance_is_allowed(weather, superadmin_client):
    Plugin.objects.filter(pk=weather.pk).update(state=PluginState.MAINTENANCE)

    assert _upload(superadmin_client, weather_manifest("0.7.0")).status_code == 201


def test_the_approval_checks_the_rules_again_against_the_ledger_as_it_is_then(
    weather, newer, superadmin_client
):
    package = newer("0.7.0")
    record = PluginDatabase.objects.get(plugin=weather)
    record.ledger = [*record.ledger, {"name": "002_conditions.sql", "sha256": digest(b"applied meanwhile\n")}]
    record.save(update_fields=["ledger"])

    response = superadmin_client.post(
        f"{PACKAGES_URL}{package.pk}/approve/",
        {
            "untrusted_acknowledged": True,
            "access_growth_acknowledged": True,
            "reviewed_against_package_id": weather.current_package_id,
        },
        format="json",
    )

    assert (response.status_code, response.json()["code"]) == (409, "plugin_upgrade_unavailable")
    package.refresh_from_db()
    assert package.review_state == ReviewState.PENDING
