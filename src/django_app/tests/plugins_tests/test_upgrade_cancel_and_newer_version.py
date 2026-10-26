"""Cancelling an upgrade, and a newer version taking the place of a failed target."""

import pytest
from plugins.models import (
    ActivityAction,
    GrantState,
    Plugin,
    PluginActivityEvent,
    PluginDatabase,
    PluginDatabaseRestore,
    PluginGrant,
    PluginPackage,
    PluginPlacement,
    PluginState,
    PluginUpgrade,
    UpgradeStage,
)
from plugins.packages.spa_publisher import MAINTENANCE_FLAG

from tests.plugins_tests.conftest import upload_file
from tests.plugins_tests.package_builder import GEOCODING_HOST, build_package, sample_files
from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    FORECAST_HOST,
    SECOND_MIGRATION_SQL,
    active_grant,
    advance_url,
    backup_body,
    ledger_of,
    newer,
    placement_of,
    upgrade_of,
    upload,
    weather,
    weather_manifest,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PLUGIN_URL = "/api/admin/plugins/weather/"


def _cancel(client):
    return client.post(f"{PLUGIN_URL}upgrade/cancel/")


def _to(node_client, upgrade, stage, capture):
    with capture(execute=True):
        assert node_client.post(advance_url(upgrade.pk), {"to": "maintenance"}, format="json").status_code == 204
    if stage == "migrating":
        body = {"to": "migrations", "backup": backup_body(upgrade)}
        assert node_client.post(advance_url(upgrade.pk), body, format="json").status_code == 204
    upgrade.refresh_from_db()
    return upgrade


def _fail(upgrade):
    PluginUpgrade.objects.filter(pk=upgrade.pk).update(failed_at=upgrade.started_at, step="migrate", last_error="boom")


def _ledger(weather, *extra):
    PluginDatabase.objects.filter(plugin=weather).update(ledger=ledger_of(weather.current_package, *extra))


def test_a_cancel_while_preparing_leaves_the_plugin_running_and_deletes_the_target(
    weather, newer, upgrade_of, superadmin_client, spa_root, package_store, django_capture_on_commit_callbacks
):
    upgrade = upgrade_of(newer())
    target = PluginPackage.objects.get(pk=upgrade.to_package_id)
    generation = placement_of(weather).restart_generation

    with django_capture_on_commit_callbacks(execute=True):
        response = _cancel(superadmin_client)

    assert response.status_code == 200, response.content
    assert (response.json()["state"], response.json()["open_upgrade"]) == ("running", None)
    upgrade.refresh_from_db()
    assert (upgrade.stage, upgrade.finished_at is not None) == (UpgradeStage.CANCELLED, True)
    assert not PluginPackage.objects.filter(pk=target.pk).exists()
    assert target.storage_key not in package_store.objects
    assert not (spa_root / "weather" / "0.7.0").exists()
    assert placement_of(weather).restart_generation == generation
    assert PluginActivityEvent.objects.get(action=ActivityAction.PLUGIN_UPGRADE_CANCELLED).detail == {
        "to_version": "0.7.0",
        "stage": "preparing",
    }


def test_a_cancel_in_maintenance_brings_the_current_version_back_and_settles_the_grants(
    weather, newer, upgrade_of, node_client, superadmin_client, superadmin, acme, spa_root, django_capture_on_commit_callbacks
):
    grant = active_grant(weather, acme, superadmin)
    upgrade = _to(node_client, upgrade_of(newer()), "maintenance", django_capture_on_commit_callbacks)
    generation = placement_of(weather).restart_generation

    with django_capture_on_commit_callbacks(execute=True):
        assert _cancel(superadmin_client).status_code == 200

    assert Plugin.objects.get(pk=weather.pk).state == PluginState.PROVISIONING
    assert placement_of(weather).restart_generation == generation + 1
    grant.refresh_from_db()
    assert (grant.state, grant.installed_version) == (GrantState.ACTIVE, "0.6.0")
    assert not (spa_root / "weather" / MAINTENANCE_FLAG).exists()
    assert upgrade.pk


def test_a_failed_migration_that_changed_nothing_can_be_cancelled(
    weather, newer, upgrade_of, node_client, superadmin_client, django_capture_on_commit_callbacks
):
    upgrade = _to(node_client, upgrade_of(newer()), "migrating", django_capture_on_commit_callbacks)
    _fail(upgrade)

    assert _cancel(superadmin_client).status_code == 200


def test_a_migration_of_the_new_version_in_the_ledger_prevents_the_cancel(
    weather, newer, upgrade_of, node_client, superadmin_client, django_capture_on_commit_callbacks
):
    upgrade = _to(node_client, upgrade_of(newer()), "migrating", django_capture_on_commit_callbacks)
    _fail(upgrade)
    _ledger(weather, ("002_conditions.sql", SECOND_MIGRATION_SQL))

    response = _cancel(superadmin_client)

    assert (response.status_code, response.json()["code"]) == (409, "upgrade_not_cancellable")
    detail = superadmin_client.get(PLUGIN_URL).json()
    assert detail["open_upgrade"]["database_changed"] is True
    assert "cancel_upgrade" not in detail["allowed_actions"]


def test_after_a_restore_the_upgrade_can_be_cancelled_again(
    weather, newer, upgrade_of, node_client, superadmin_client, django_capture_on_commit_callbacks
):
    upgrade = _to(node_client, upgrade_of(newer()), "migrating", django_capture_on_commit_callbacks)
    _fail(upgrade)
    _ledger(weather, ("002_conditions.sql", SECOND_MIGRATION_SQL))
    assert _cancel(superadmin_client).status_code == 409

    _ledger(weather)

    assert _cancel(superadmin_client).status_code == 200


def test_a_migrating_upgrade_still_working_cannot_be_cancelled(
    weather, newer, upgrade_of, node_client, superadmin_client, django_capture_on_commit_callbacks
):
    _to(node_client, upgrade_of(newer()), "migrating", django_capture_on_commit_callbacks)

    assert _cancel(superadmin_client).json()["code"] == "upgrade_not_cancellable"


def test_an_upgrade_that_adds_a_backend_cannot_be_cancelled(
    running_plugin, installation, superadmin, superadmin_client, plugin_node, plugin_database_server, upgrade_of
):
    running_plugin(version="0.6.0")
    manifest = weather_manifest("0.7.0")
    upgrade_of(upload(installation, superadmin, manifest, sample_files(manifest)))

    response = _cancel(superadmin_client)

    assert (response.status_code, response.json()["code"]) == (409, "upgrade_not_cancellable")


def test_an_open_restore_prevents_the_cancel(
    weather, newer, upgrade_of, node_client, superadmin_client, superadmin, django_capture_on_commit_callbacks
):
    upgrade = _to(node_client, upgrade_of(newer()), "migrating", django_capture_on_commit_callbacks)
    _fail(upgrade)
    upgrade.refresh_from_db()
    PluginDatabaseRestore.objects.create(
        plugin_database=PluginDatabase.objects.get(plugin=weather),
        upgrade=upgrade,
        backup=upgrade.backup,
        backup_file_name=upgrade.backup.file_name,
        requested_by=superadmin,
    )

    assert _cancel(superadmin_client).json()["code"] == "upgrade_not_cancellable"


def test_without_an_open_upgrade_there_is_nothing_to_cancel(weather, superadmin_client):
    assert _cancel(superadmin_client).json()["code"] == "upgrade_not_cancellable"


def test_the_cancelled_version_can_be_uploaded_again(weather, newer, upgrade_of, superadmin_client):
    upgrade_of(newer())
    _cancel(superadmin_client)

    data = build_package(manifest=weather_manifest("0.7.0"))
    response = superadmin_client.post("/api/admin/plugins/packages/", {"file": upload_file(data)}, format="multipart")

    assert response.status_code == 201


# ---- a newer version for a failed upgrade ----


def test_a_newer_version_takes_a_failed_target_s_place_in_the_same_upgrade(
    weather, newer, upgrade_of, node_client, spa_root, package_store, django_capture_on_commit_callbacks
):
    upgrade = _to(node_client, upgrade_of(newer("0.7.0")), "migrating", django_capture_on_commit_callbacks)
    _fail(upgrade)
    upgrade.refresh_from_db()
    old_target = PluginPackage.objects.get(pk=upgrade.to_package_id)
    backup_id = upgrade.backup_id
    generation = placement_of(weather).restart_generation

    replaced = upgrade_of(newer("0.7.1"))

    assert replaced.pk == upgrade.pk
    assert (replaced.to_version, replaced.stage) == ("0.7.1", UpgradeStage.MAINTENANCE)
    assert (replaced.failed_at, replaced.last_error, replaced.step) == (None, None, None)
    assert replaced.backup_id == backup_id
    assert not PluginPackage.objects.filter(pk=old_target.pk).exists()
    assert old_target.storage_key not in package_store.objects
    assert not (spa_root / "weather" / "0.7.0").exists()
    assert placement_of(weather).restart_generation == generation + 1
    started = PluginActivityEvent.objects.filter(action=ActivityAction.PLUGIN_UPGRADE_STARTED).order_by("pk")
    assert [event.detail["replaced_version"] for event in started] == [None, "0.7.0"]
    desired = node_client.get("/api/plugin-nodes/self/desired-state/").json()["placements"][0]
    assert (desired["upgrade"]["backup"], desired["package"]["version"]) == ("taken", "0.7.1")


def test_a_newer_version_for_a_failed_preparation_keeps_preparing(weather, newer, upgrade_of):
    upgrade = upgrade_of(newer("0.7.0"))
    _fail(upgrade)

    replaced = upgrade_of(newer("0.7.1"))

    assert (replaced.pk, replaced.stage) == (upgrade.pk, UpgradeStage.PREPARING)


def test_the_growth_of_a_replacement_is_computed_against_the_failed_target(weather, newer, upgrade_of, superadmin_client):
    upgrade = upgrade_of(newer("0.7.0", outbound_hosts=[GEOCODING_HOST, FORECAST_HOST]))
    _fail(upgrade)
    package = newer("0.7.1", outbound_hosts=[GEOCODING_HOST, FORECAST_HOST])

    response = superadmin_client.post(
        f"/api/admin/plugins/packages/{package.pk}/approve/",
        {"untrusted_acknowledged": True, "reviewed_against_package_id": upgrade.to_package_id},
        format="json",
    )

    assert response.status_code == 202, response.content


def test_a_working_upgrade_is_not_replaced(weather, newer, upgrade_of, superadmin_client):
    upgrade = upgrade_of(newer("0.7.0"))
    package = newer("0.7.1")

    response = superadmin_client.post(
        f"/api/admin/plugins/packages/{package.pk}/approve/",
        {"untrusted_acknowledged": True, "access_growth_acknowledged": True, "reviewed_against_package_id": upgrade.to_package_id},
        format="json",
    )

    assert (response.status_code, response.json()["code"]) == (409, "plugin_not_upgradable")
    assert PluginUpgrade.objects.get(pk=upgrade.pk).to_version == "0.7.0"


def test_the_grants_stay_offline_while_a_replacement_is_prepared(
    weather, newer, upgrade_of, node_client, superadmin, acme, django_capture_on_commit_callbacks
):
    grant = active_grant(weather, acme, superadmin)
    upgrade = _to(node_client, upgrade_of(newer("0.7.0")), "migrating", django_capture_on_commit_callbacks)
    _fail(upgrade)

    upgrade_of(newer("0.7.1"))

    assert PluginGrant.objects.get(pk=grant.pk).state == GrantState.UPGRADING
    assert Plugin.objects.get(pk=weather.pk).state == PluginState.MAINTENANCE
    assert PluginPlacement.objects.filter(plugin=weather).exists()
