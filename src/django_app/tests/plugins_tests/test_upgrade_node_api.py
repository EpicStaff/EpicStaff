"""The node's side of an upgrade: what its desired state says per stage, and its two requests."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from plugins.lifecycle.upgrade_service import PluginUpgradeService
from plugins.models import (
    ActivityAction,
    GrantState,
    HookJobKind,
    Plugin,
    PluginActivityEvent,
    PluginDatabaseBackup,
    PluginGrant,
    PluginHookJob,
    PluginState,
    PluginUpgrade,
    UpgradeStage,
)
from plugins.nodes.desired_state_builder import DesiredStateBuilder
from plugins.packages.spa_publisher import MAINTENANCE_FLAG

from tests.plugins_tests.conftest import mark_running
from tests.plugins_tests.package_builder import GEOCODING_HOST, PING_PATH, UNITS_SETTING
from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    FORECAST_HOST,
    active_grant,
    advance_url,
    backup_body,
    database_ready,
    newer,
    placement_of,
    upgrade_of,
    upload,
    weather,
    weather_manifest,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

DESIRED_STATE_URL = "/api/plugin-nodes/self/desired-state/"
STATUS_PATH = {**PING_PATH, "path": "/api/status"}


@pytest.fixture
def upgrade(weather, newer, upgrade_of, superadmin, acme):
    active_grant(weather, acme, superadmin)
    return upgrade_of(
        newer(
            outbound_hosts=[GEOCODING_HOST, FORECAST_HOST],
            public_paths=[PING_PATH, STATUS_PATH],
            limits={"memory_mb": 512, "db_connections": 5, "statement_timeout_seconds": 10, "requests_per_minute": 120, "cpu_priority": "normal"},
        )
    )


def _advance(node_client, upgrade, to, backup=None):
    body = {"to": to} if backup is None else {"to": to, "backup": backup}
    return node_client.post(advance_url(upgrade.pk), body, format="json")


def _to_maintenance(node_client, upgrade, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        assert _advance(node_client, upgrade, "maintenance").status_code == 204
    upgrade.refresh_from_db()
    return upgrade


def _placement(node_client):
    return node_client.get(DESIRED_STATE_URL).json()["placements"][0]


# ---- advance to maintenance ----


def test_maintenance_stops_the_plugin_and_takes_its_organizations_offline(
    upgrade, weather, node_client, superadmin, beta, spa_root, django_capture_on_commit_callbacks
):
    failed = active_grant(weather, beta, superadmin)
    PluginGrant.objects.filter(pk=failed.pk).update(state=GrantState.UPGRADE_FAILED)

    _to_maintenance(node_client, upgrade, django_capture_on_commit_callbacks)

    assert (upgrade.stage, upgrade.maintenance_started_at is not None) == (UpgradeStage.MAINTENANCE, True)
    assert Plugin.objects.get(pk=weather.pk).state == PluginState.MAINTENANCE
    states = dict(PluginGrant.objects.filter(plugin=weather).values_list("org__name", "state"))
    assert states == {"Acme-xorg": GrantState.UPGRADING, "Beta-xorg": GrantState.UPGRADE_FAILED}
    assert not PluginHookJob.objects.filter(kind=HookJobKind.UPGRADE).exists()
    assert (spa_root / "weather" / MAINTENANCE_FLAG).is_file()
    event = PluginActivityEvent.objects.get(action=ActivityAction.PLUGIN_MAINTENANCE_STARTED)
    assert event.detail == {"to_version": "0.7.0", "organizations": 1}


def test_asking_for_maintenance_again_changes_nothing(upgrade, node_client, django_capture_on_commit_callbacks):
    _to_maintenance(node_client, upgrade, django_capture_on_commit_callbacks)

    assert _advance(node_client, upgrade, "maintenance").status_code == 204
    assert PluginActivityEvent.objects.filter(action=ActivityAction.PLUGIN_MAINTENANCE_STARTED).count() == 1


def test_a_failed_or_cancelled_upgrade_cannot_advance(upgrade, node_client, superadmin):
    PluginUpgrade.objects.filter(pk=upgrade.pk).update(failed_at=upgrade.started_at)
    failed = _advance(node_client, upgrade, "maintenance")
    PluginUpgrade.objects.filter(pk=upgrade.pk).update(failed_at=None)
    PluginUpgradeService().cancel("weather", superadmin)
    cancelled = _advance(node_client, upgrade, "maintenance")

    assert [failed.json()["code"], cancelled.json()["code"]] == ["upgrade_not_current"] * 2
    assert failed.status_code == cancelled.status_code == 409


def test_migrations_cannot_come_before_maintenance(upgrade, node_client):
    response = _advance(node_client, upgrade, "migrations")

    assert (response.status_code, response.json()["code"]) == (409, "upgrade_not_current")


def test_another_node_s_upgrade_is_not_found(upgrade, other_node, other_node_client):
    response = other_node_client.post(advance_url(upgrade.pk), {"to": "maintenance"}, format="json")

    assert (response.status_code, response.json()["code"]) == (404, "upgrade_not_found")


def test_a_plugin_that_failed_or_restarted_while_preparing_can_still_be_stopped(upgrade, weather, node_client):
    Plugin.objects.filter(pk=weather.pk).update(state=PluginState.PROVISIONING)

    assert _advance(node_client, upgrade, "maintenance").status_code == 204


# ---- advance to migrations ----


@pytest.mark.parametrize(
    ("change", "loc"),
    [
        ({"backup": None}, "advance.backup"),
        ({"installation_id": "0" * 32}, "advance.backup.installation_id"),
        ({"version": "0.5.0"}, "advance.backup.version"),
    ],
)
def test_the_migrations_need_this_upgrade_s_backup(upgrade, node_client, django_capture_on_commit_callbacks, change, loc):
    _to_maintenance(node_client, upgrade, django_capture_on_commit_callbacks)
    backup = None if "backup" in change else {**backup_body(upgrade), **change}

    response = _advance(node_client, upgrade, "migrations", backup)

    assert (response.status_code, response.json()["code"]) == (400, "invalid_upgrade_advance")
    assert response.json()["errors"][0]["loc"] == loc
    upgrade.refresh_from_db()
    assert (upgrade.stage, upgrade.backup_id) == (UpgradeStage.MAINTENANCE, None)


@pytest.mark.parametrize(
    "change",
    [{"upgrade_id": 999999}, {"reason": "pre_restore"}],
)
def test_a_backup_of_another_upgrade_or_reason_is_refused(upgrade, node_client, django_capture_on_commit_callbacks, change):
    _to_maintenance(node_client, upgrade, django_capture_on_commit_callbacks)

    response = _advance(node_client, upgrade, "migrations", backup_body(upgrade, **change))

    assert (response.status_code, response.json()["code"]) == (400, "invalid_upgrade_advance")


def test_the_backup_is_recorded_with_its_activity_and_the_migrations_may_run(upgrade, node_client, django_capture_on_commit_callbacks):
    _to_maintenance(node_client, upgrade, django_capture_on_commit_callbacks)
    body = backup_body(upgrade)

    assert _advance(node_client, upgrade, "migrations", body).status_code == 204

    upgrade.refresh_from_db()
    backup = PluginDatabaseBackup.objects.get()
    assert (upgrade.stage, upgrade.backup_id, upgrade.migrations_started_at is not None) == (
        UpgradeStage.MIGRATING,
        backup.pk,
        True,
    )
    assert (backup.file_name, backup.reason, backup.version, backup.upgrade_id) == (
        body["file_name"],
        "pre_upgrade",
        "0.6.0",
        upgrade.pk,
    )
    assert PluginActivityEvent.objects.get(action=ActivityAction.DATABASE_BACKED_UP).detail == {
        "file_name": body["file_name"],
        "reason": "pre_upgrade",
        "size_bytes": body["size_bytes"],
        "version": "0.6.0",
    }


def test_asking_for_the_migrations_again_with_the_same_backup_changes_nothing(upgrade, node_client, django_capture_on_commit_callbacks):
    _to_maintenance(node_client, upgrade, django_capture_on_commit_callbacks)
    body = backup_body(upgrade)
    _advance(node_client, upgrade, "migrations", body)

    again = _advance(node_client, upgrade, "migrations", body)
    other = _advance(node_client, upgrade, "migrations", {**body, "sha256": "f" * 64})

    assert again.status_code == 204
    assert (other.status_code, other.json()["code"]) == (400, "invalid_upgrade_advance")
    assert PluginActivityEvent.objects.filter(action=ActivityAction.DATABASE_BACKED_UP).count() == 1


def test_a_plugin_without_a_database_ready_needs_no_backup(weather, newer, upgrade_of, node_client, django_capture_on_commit_callbacks):
    from plugins.models import PluginDatabase

    PluginDatabase.objects.filter(plugin=weather).update(ready_at=None)
    upgrade = upgrade_of(newer())
    _to_maintenance(node_client, upgrade, django_capture_on_commit_callbacks)

    assert _advance(node_client, upgrade, "migrations").status_code == 204
    assert _advance(node_client, upgrade, "migrations", backup_body(upgrade)).status_code == 400


def test_a_body_that_is_not_a_request_is_refused_where_it_is_wrong(upgrade, node_client):
    response = node_client.post(advance_url(upgrade.pk), {"to": "done"}, format="json")

    assert (response.status_code, response.json()["code"]) == (400, "invalid_upgrade_advance")
    assert response.json()["errors"][0]["loc"].startswith("advance.to")


# ---- the desired state, stage by stage ----


def test_while_preparing_the_node_runs_the_current_version_and_gets_the_target_ready(upgrade, weather, node_client):
    placement = _placement(node_client)

    assert placement["package"]["version"] == "0.6.0"
    assert placement["runtime"]["memory_mb"] == 256
    assert placement["egress"]["hosts"] == [GEOCODING_HOST["host"]]
    assert placement["upgrade"]["stage"] == "preparing"
    assert placement["upgrade"]["target"]["version"] == "0.7.0"
    assert placement["upgrade"]["target"]["package_id"] == upgrade.to_package_id
    assert placement["upgrade"]["target_runtime"]["memory_mb"] == 512
    assert (placement["upgrade"]["backup"], placement["upgrade"]["backup_bytes_needed"]) == ("required", 4096)


def test_from_maintenance_on_the_node_runs_the_target_and_lists_no_hook(
    upgrade, weather, node_client, superadmin, beta, django_capture_on_commit_callbacks
):
    granting = PluginGrant.objects.create(plugin=weather, org=beta, state=GrantState.GRANTING, created_by=superadmin)
    from plugins.lifecycle.hook_job_service import HookJobService

    HookJobService().create_install_job(granting, weather.current_package)
    assert _placement(node_client)["hook_jobs"]
    _to_maintenance(node_client, upgrade, django_capture_on_commit_callbacks)

    placement = _placement(node_client)

    assert placement["package"]["version"] == "0.7.0"
    assert placement["runtime"] == placement["upgrade"]["target_runtime"]
    assert placement["egress"]["hosts"] == [GEOCODING_HOST["host"], FORECAST_HOST["host"]]
    assert placement["database"]["database_name"] == "plugin_weather"
    assert placement["hook_jobs"] == []
    assert placement["upgrade"]["stage"] == "maintenance"


def test_a_recorded_backup_is_taken_and_old_backups_are_listed_for_deletion(upgrade, weather, node_client, django_capture_on_commit_callbacks):
    _to_maintenance(node_client, upgrade, django_capture_on_commit_callbacks)
    _advance(node_client, upgrade, "migrations", backup_body(upgrade))
    record = upgrade.plugin.database
    PluginDatabaseBackup.objects.create(
        plugin_database=record,
        file_name="20250101T000000Z-u1-pre_upgrade.dump",
        reason="pre_upgrade",
        version="0.5.0",
        size_bytes=10,
        sha256="a" * 64,
        created_at="2025-01-01T00:00:00Z",
    )

    placement = _placement(node_client)

    assert placement["upgrade"]["backup"] == "taken"
    assert placement["backups_to_delete"] == ["20250101T000000Z-u1-pre_upgrade.dump"]


def test_the_target_is_downloadable_only_by_its_node(upgrade, node_client, other_node, other_node_client, package_store):
    url = f"/api/plugin-nodes/self/packages/{upgrade.to_package_id}/"

    assert node_client.get(url).status_code == 200
    assert other_node_client.get(url).status_code == 404


def test_from_maintenance_on_the_runtime_file_is_the_target_s_with_keys_for_upgrading_organizations(
    upgrade, weather, node_client, acme, django_capture_on_commit_callbacks
):
    _to_maintenance(node_client, upgrade, django_capture_on_commit_callbacks)

    credentials = node_client.post(
        f"/api/plugin-nodes/self/placements/{placement_of(weather).pk}/runtime-credentials/"
    ).json()

    runtime_file = credentials["runtime_file"]
    assert runtime_file["plugin"]["version"] == "0.7.0"
    assert [path["path"] for path in runtime_file["public_paths"]] == ["/api/ping", "/api/status"]
    assert runtime_file["service_accounts"][str(acme.pk)]["grant_state"] == "upgrading"
    assert set(runtime_file["settings"]) == {UNITS_SETTING["key"]}
    assert credentials["database"]["app_password"]


def test_the_desired_state_costs_the_same_queries_for_one_upgrade_and_for_five(
    database_plugin, installation, superadmin, plugin_node, django_capture_on_commit_callbacks
):
    from tests.plugins_tests.upgrade_fixtures import start_upgrade

    def queries_of_build():
        DesiredStateBuilder().build(plugin_node)
        with CaptureQueriesContext(connection) as captured:
            DesiredStateBuilder().build(plugin_node)
        return len(captured.captured_queries)

    def upgrading(identifier):
        plugin = mark_running(database_plugin(id=identifier, version="0.6.0"))
        database_ready(plugin)
        package = upload(installation, superadmin, weather_manifest("0.7.0", id=identifier))
        start_upgrade(installation, superadmin, package, django_capture_on_commit_callbacks)

    upgrading("weather")
    with_one = queries_of_build()
    for identifier in ("forecast", "tides", "winds", "storms"):
        upgrading(identifier)

    assert queries_of_build() == with_one
