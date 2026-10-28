"""A node's backup inventory in its reports: which rows a report locks and how it records new
ones, and a restore's way back linked once a report lists it."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from loguru import logger as loguru_logger
from django.utils import timezone
from plugins.lifecycle.upgrade_service import PluginUpgradeService
from plugins.models import PluginDatabaseBackup, PluginDatabaseRestore, PluginUpgrade
from src.shared.models.plugin_nodes import PlacementReport

from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    TAKEN_AT,
    advance_url,
    backup_body,
    database_report,
    newer,
    placement_of,
    send_report,
    upgrade_of,
    weather,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

BACKUPS = '"plugins_plugindatabasebackup"'


@pytest.fixture
def failed_migration(weather, newer, upgrade_of, node_client, django_capture_on_commit_callbacks):
    upgrade = upgrade_of(newer())
    with django_capture_on_commit_callbacks(execute=True):
        node_client.post(advance_url(upgrade.pk), {"to": "maintenance"}, format="json")
    node_client.post(advance_url(upgrade.pk), {"to": "migrations", "backup": backup_body(upgrade)}, format="json")
    PluginUpgrade.objects.filter(pk=upgrade.pk).update(failed_at=upgrade.started_at, step="migrate", last_error="boom")
    upgrade.refresh_from_db()
    return upgrade


def _pre_restore(upgrade, minutes: int) -> dict:
    return backup_body(upgrade, reason="pre_restore", taken_at=TAKEN_AT + timedelta(minutes=minutes))


def _report_queries(node_client, weather, backups) -> list[str]:
    with CaptureQueriesContext(connection) as captured:
        send_report(node_client, weather, database=database_report(weather), backups=backups)
    return [query["sql"] for query in captured.captured_queries]


def test_a_report_listing_known_unchanged_backups_locks_none_of_them(failed_migration, weather, node_client):
    listed = [backup_body(failed_migration), *(_pre_restore(failed_migration, minutes) for minutes in (1, 2))]
    send_report(node_client, weather, database=database_report(weather), backups=listed)

    queries = _report_queries(node_client, weather, listed)

    locking_backups = [
        sql
        for sql in queries
        if sql.startswith(f"SELECT {BACKUPS}.") and (" FOR UPDATE" in sql or " FOR NO KEY UPDATE" in sql)
    ]
    assert not locking_backups
    # The unlisted ones are marked deleted by one UPDATE, which matches none of these.
    assert not [
        sql
        for sql in queries
        if sql.startswith(f'UPDATE {BACKUPS} SET "sha256_mismatch"') or 'SET "deleted_at" = NULL' in sql
    ]


def test_a_backup_listed_with_another_sha256_is_marked_by_an_update_of_that_row_alone(
    failed_migration, weather, node_client
):
    other = _pre_restore(failed_migration, 1)
    send_report(node_client, weather, database=database_report(weather), backups=[backup_body(failed_migration), other])

    send_report(
        node_client, weather, database=database_report(weather), backups=[backup_body(failed_migration, sha256="f" * 64), other]
    )

    mismatched = PluginDatabaseBackup.objects.filter(sha256_mismatch=True).values_list("file_name", flat=True)
    assert list(mismatched) == [backup_body(failed_migration)["file_name"]]


def test_new_backups_cost_the_same_upgrade_lookups_however_many_there_are(failed_migration, weather, node_client):
    def upgrade_lookups(listed) -> int:
        return sum('FROM "plugins_pluginupgrade"' in sql for sql in _report_queries(node_client, weather, listed))

    two = [backup_body(failed_migration), *(_pre_restore(failed_migration, minutes) for minutes in (1, 2))]
    fourteen = [*two, *(_pre_restore(failed_migration, minutes) for minutes in range(3, 15))]

    assert upgrade_lookups(two) == upgrade_lookups(fourteen)
    recorded = PluginDatabaseBackup.objects.filter(reason="pre_restore")
    assert (recorded.count(), set(recorded.values_list("upgrade_id", flat=True))) == (14, {failed_migration.pk})


def test_a_backup_naming_another_plugin_s_upgrade_is_recorded_without_one(
    failed_migration, weather, node_client, database_plugin
):
    other = database_plugin(id="tides")
    foreign = PluginUpgrade.objects.create(plugin=other, from_version="0.1.0", to_version="0.2.0", stage="done")
    body = backup_body(failed_migration, reason="pre_restore", upgrade_id=foreign.pk)

    send_report(node_client, weather, database=database_report(weather), backups=[body])

    assert PluginDatabaseBackup.objects.get(file_name=body["file_name"]).upgrade_id is None


def _restore_reported(superadmin_client, node_client, weather, failed_migration, *, state, step, pre_restore, backups=None):
    response = superadmin_client.post(
        f"/api/admin/plugins/weather/backups/{failed_migration.backup_id}/restore/",
        {"verification_phrase": "restore-weather"},
        format="json",
    )
    assert response.status_code == 202, response.content
    restore = PluginDatabaseRestore.objects.order_by("-pk").first()
    send_report(
        node_client,
        weather,
        observed_state="stopped",
        health="unknown",
        **({} if backups is None else {"backups": backups}),
        restore={"restore_id": restore.pk, "state": state, "step": step, "pre_restore_backup": pre_restore},
    )
    restore.refresh_from_db()
    return restore


@pytest.mark.parametrize(("state", "step"), [("succeeded", "assert"), ("failed", "recreate")])
def test_a_pre_restore_backup_listed_only_after_the_restore_ended_is_linked_then(
    failed_migration, weather, superadmin_client, node_client, state, step
):
    pre_restore = _pre_restore(failed_migration, 5)
    restore = _restore_reported(
        superadmin_client, node_client, weather, failed_migration, state=state, step=step, pre_restore=pre_restore["file_name"]
    )
    assert (restore.state, restore.pre_restore_backup_id) == (state, None)

    send_report(node_client, weather, database=database_report(weather), backups=[backup_body(failed_migration), pre_restore])

    restore.refresh_from_db()
    assert restore.pre_restore_backup.file_name == pre_restore["file_name"]


def test_a_pre_restore_backup_listed_in_the_same_report_is_linked_at_once(
    failed_migration, weather, superadmin_client, node_client
):
    pre_restore = _pre_restore(failed_migration, 5)

    restore = _restore_reported(
        superadmin_client,
        node_client,
        weather,
        failed_migration,
        state="succeeded",
        step="assert",
        pre_restore=pre_restore["file_name"],
        backups=[backup_body(failed_migration), pre_restore],
    )

    assert restore.pre_restore_backup.file_name == pre_restore["file_name"]


def test_a_report_follow_up_that_finds_its_plugin_held_logs_that_it_skipped(weather, plugin_node):
    messages = []
    sink = loguru_logger.add(lambda message: messages.append(message.record["message"]), level="DEBUG")
    placement = placement_of(weather)
    try:
        # Another node's placement id: the follow-up finds no plugin it may lock, as when one is held.
        PluginUpgradeService().follow_report(
            plugin_node,
            placement.pk + 1000,
            PlacementReport(placement_id=placement.pk + 1000, observed_state="running", health="ok", restarts=0),
            timezone.now(),
        )
    finally:
        loguru_logger.remove(sink)

    assert f"Placement {placement.pk + 1000}'s plugin is locked or gone; its report is applied with the next one" in messages
