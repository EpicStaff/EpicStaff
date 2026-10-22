"""Two connections at once on an upgrade's rows: no deadlock, and no transaction rolled back.

Each test pauses one side inside the real code path (a wrapper that calls the original, then
holds its transaction open), starts the other side on its own connection, waits until that one
blocks or finishes, then lets the first go on. Committed data: transactional tests.
"""

import json
import threading
import time

import pytest
from django.db import connection
from django.utils import timezone
from plugins.lifecycle.upgrade_service import PluginUpgradeService
from plugins.models import (
    HookJobKind,
    Plugin,
    PluginDatabaseBackup,
    PluginHookJob,
    PluginPackage,
    PluginUpgrade,
    UpgradeStage,
)
from plugins.nodes import node_report_service
from plugins.nodes.node_report_service import NodeReportService
from rbac.governance.organizations import OrganizationManagementService
from rbac.models import Organization
from src.shared.models.plugin_nodes import NodeReport, PlacementReport

from tests.plugins_tests.conftest import mark_running
from tests.plugins_tests.upgrade_fixtures import (
    active_grant,
    backup_body,
    database_ready,
    placement_of,
    start_upgrade,
    upload,
    weather_manifest,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root"),
]

# Postgres reports a deadlock after `deadlock_timeout` (1 s); a lock wait that is not one ends
# when the paused side lets go.
LOCK_TIMEOUT = "15s"


class Paused:
    """Wraps a callable: runs it, then holds the caller's transaction open until `release()`."""

    def __init__(self, original):
        self.original = original
        self.reached = threading.Event()
        self._go = threading.Event()

    def __call__(self, *args, **kwargs):
        result = self.original(*args, **kwargs)
        self.reached.set()
        self._go.wait(20)
        return result

    def release(self):
        self._go.set()


class Side(threading.Thread):
    """Runs `work` on a connection of its own, with a lock timeout."""

    def __init__(self, name, work):
        super().__init__(name=name, daemon=True)
        self._work = work
        self.error = None
        self.seconds = None

    def run(self):
        started = time.perf_counter()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
            self._work()
        except BaseException as error:  # noqa: BLE001 - asserted by the test
            self.error = error
        finally:
            self.seconds = time.perf_counter() - started
            connection.close()


def _blocked_or_done(other: Side) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
            "AND pid <> pg_backend_pid() AND wait_event_type = 'Lock'"
        )
        waiting = cursor.fetchone()[0]
    return waiting > 0 or not other.is_alive()


def _run_pair(first: Side, second: Side, paused: Paused) -> None:
    first.start()
    assert paused.reached.wait(15), "the first side never reached its pause"
    second.start()
    deadline = time.monotonic() + 10
    while not _blocked_or_done(second) and time.monotonic() < deadline:
        time.sleep(0.05)
    paused.release()
    first.join(40)
    second.join(40)
    assert (first.error, second.error) == (None, None)


@pytest.fixture
def upgrading_weather(database_plugin, installation, superadmin, plugin_node, django_capture_on_commit_callbacks):
    """Factory → Weather 0.6.0 with its database, upgrading to 0.7.0 and stopped for it."""

    def _make(hooks=None):
        changes = {"id": "weather", "version": "0.6.0", **({"hooks": hooks} if hooks else {})}
        plugin = mark_running(database_plugin(**changes))
        database_ready(plugin)
        package = upload(
            installation, superadmin, weather_manifest("0.7.0", id="weather", **({"hooks": hooks} if hooks else {}))
        )
        upgrade = start_upgrade(installation, superadmin, package, django_capture_on_commit_callbacks)
        PluginUpgradeService().advance(plugin_node, upgrade.pk, _advance("maintenance"))
        return Plugin.objects.select_related("current_package").get(pk=plugin.pk), upgrade

    return _make


def _advance(to: str, backup: dict | None = None) -> bytes:
    return json.dumps({"to": to, **({"backup": backup} if backup else {})}).encode()


def _report_listing(plugin: Plugin, backups: list[dict]) -> NodeReport:
    placement = placement_of(plugin)
    return NodeReport.model_validate(
        {
            "format": 1,
            "agent_version": "0.1.0",
            "reported_at": "2026-10-21T12:00:05Z",
            "placements": [
                {
                    "placement_id": placement.pk,
                    "observed_state": "stopped",
                    "observed_version": "0.6.0",
                    "health": "unknown",
                    "restarts": 0,
                    "applied_settings_revision": placement.settings_revision,
                    "applied_restart_generation": placement.restart_generation,
                    "backups": backups,
                }
            ],
        }
    )


def test_a_report_recording_a_backup_and_a_cancel_both_finish(upgrading_weather, superadmin, plugin_node, monkeypatch):
    plugin, upgrade = upgrading_weather()
    paused = Paused(node_report_service.mark_unlisted_deleted)
    monkeypatch.setattr(node_report_service, "mark_unlisted_deleted", paused)
    report = _report_listing(plugin, [backup_body(upgrade)])

    _run_pair(
        Side("report", lambda: NodeReportService().record(plugin_node, report)),
        Side("cancel", lambda: PluginUpgradeService().cancel("weather", superadmin)),
        paused,
    )

    upgrade.refresh_from_db()
    assert upgrade.stage == UpgradeStage.CANCELLED
    assert PluginDatabaseBackup.objects.count() == 1


@pytest.mark.parametrize("first", ["report", "advance"])
def test_a_report_and_the_migrations_request_recording_the_same_backup_both_finish(
    upgrading_weather, plugin_node, monkeypatch, first
):
    plugin, upgrade = upgrading_weather()
    backup = backup_body(upgrade)
    report = _report_listing(plugin, [backup])
    advance = Side("advance", lambda: PluginUpgradeService().advance(plugin_node, upgrade.pk, _advance("migrations", backup)))
    reporter = Side("report", lambda: NodeReportService().record(plugin_node, report))
    if first == "report":
        paused = Paused(node_report_service.mark_unlisted_deleted)
        monkeypatch.setattr(node_report_service, "mark_unlisted_deleted", paused)
        _run_pair(reporter, advance, paused)
    else:
        paused = Paused(PluginUpgradeService._advance_to_migrations)
        monkeypatch.setattr(
            PluginUpgradeService, "_advance_to_migrations", lambda self, *args, **kwargs: paused(self, *args, **kwargs)
        )
        _run_pair(advance, reporter, paused)

    upgrade.refresh_from_db()
    recorded = PluginDatabaseBackup.objects.get()
    assert (upgrade.stage, upgrade.backup_id) == (UpgradeStage.MIGRATING, recorded.pk)


def test_an_organization_deleted_while_the_upgrade_completes_gets_its_job_on_the_new_version(
    upgrading_weather, superadmin, plugin_node, monkeypatch, mocker, acme
):
    """`acme` stays: the last active organization cannot be deleted."""
    mocker.patch("tables.services.organization_deletion.get_storage_backend").return_value.list_all_objects.return_value = []
    mocker.patch.object(OrganizationManagementService, "_deprovision_storage", lambda *args, **kwargs: None)
    plugin, upgrade = upgrading_weather(hooks={"org_removed": True})
    cobalt = Organization.objects.create(name="Cobalt")
    active_grant(plugin, cobalt, superadmin)
    superadmin.is_superadmin = True
    superadmin.save(update_fields=["is_superadmin"])
    PluginUpgradeService().advance(plugin_node, upgrade.pk, _advance("migrations", backup_body(upgrade)))
    old_package = plugin.current_package_id
    paused = Paused(PluginUpgradeService._complete)
    monkeypatch.setattr(PluginUpgradeService, "_complete", lambda self, *args, **kwargs: paused(self, *args, **kwargs))
    placement = placement_of(plugin)
    healthy = PlacementReport(
        placement_id=placement.pk,
        observed_state="running",
        observed_version="0.7.0",
        health="ok",
        restarts=0,
        applied_settings_revision=placement.settings_revision,
        applied_restart_generation=placement.restart_generation,
    )

    _run_pair(
        Side("completion", lambda: PluginUpgradeService().follow_report(plugin_node, placement.pk, healthy, timezone.now())),
        Side(
            "organization delete",
            lambda: OrganizationManagementService().delete_organization(
                superadmin, cobalt.pk, verification_phrase=f"delete-{cobalt.name}"
            ),
        ),
        paused,
    )

    assert not Organization.objects.filter(pk=cobalt.pk).exists()
    assert not PluginPackage.objects.filter(pk=old_package).exists()
    job = PluginHookJob.objects.get(organization_id=cobalt.pk, kind=HookJobKind.ORG_REMOVED)
    assert job.package_id == PluginUpgrade.objects.get(pk=upgrade.pk).to_package_id
