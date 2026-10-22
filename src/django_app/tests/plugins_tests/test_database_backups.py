"""The records of a plugin database's backups: what the node reports, retention, the list."""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from plugins.databases.backup_records import BACKUPS_KEPT, backup_retention
from plugins.models import (
    ActivityAction,
    PluginActivityEvent,
    PluginDatabase,
    PluginDatabaseBackup,
    PluginUpgrade,
)
from src.shared.models.plugin_nodes import backup_file_name

from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    advance_url,
    backup_body,
    database_report,
    newer,
    send_report,
    upgrade_of,
    weather,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=dt_timezone.utc)


def _backup(database, *, upgrade=None, reason="pre_upgrade", days_ago=0, pk_offset=1, **changes):
    taken = NOW - timedelta(days=days_ago, seconds=pk_offset)
    return PluginDatabaseBackup.objects.create(
        plugin_database=database,
        upgrade=upgrade,
        file_name=backup_file_name(taken, upgrade.pk if upgrade else pk_offset, reason),
        reason=reason,
        version="0.6.0",
        size_bytes=100,
        sha256="a" * 64,
        created_at=taken,
        **changes,
    )


@pytest.fixture
def database(weather):
    return PluginDatabase.objects.get(plugin=weather)


@pytest.fixture
def failed_migration(weather, newer, upgrade_of, node_client, django_capture_on_commit_callbacks):
    """An upgrade to 0.7.0 that failed while migrating, with its pre-upgrade backup."""
    upgrade = upgrade_of(newer())
    with django_capture_on_commit_callbacks(execute=True):
        node_client.post(advance_url(upgrade.pk), {"to": "maintenance"}, format="json")
    node_client.post(advance_url(upgrade.pk), {"to": "migrations", "backup": backup_body(upgrade)}, format="json")
    PluginUpgrade.objects.filter(pk=upgrade.pk).update(failed_at=upgrade.started_at, step="migrate")
    upgrade.refresh_from_db()
    return upgrade


# ---- what the node reports ----


def test_a_report_records_each_backup_once_with_its_activity(failed_migration, weather, node_client):
    restore_backup = backup_body(failed_migration, reason="pre_restore", taken_at=NOW)

    send_report(node_client, weather, database=database_report(weather), backups=[restore_backup])
    send_report(node_client, weather, database=database_report(weather), backups=[restore_backup])

    recorded = PluginDatabaseBackup.objects.get(file_name=restore_backup["file_name"])
    assert (recorded.reason, recorded.version, recorded.upgrade_id) == ("pre_restore", "0.7.0", failed_migration.pk)
    events = PluginActivityEvent.objects.filter(action=ActivityAction.DATABASE_BACKED_UP)
    assert events.filter(detail__file_name=restore_backup["file_name"]).count() == 1


def test_a_backup_of_another_installation_is_ignored(failed_migration, weather, node_client):
    foreign = backup_body(failed_migration, reason="pre_restore", taken_at=NOW, installation_id="b" * 32)

    send_report(node_client, weather, database=database_report(weather), backups=[foreign])

    assert not PluginDatabaseBackup.objects.filter(file_name=foreign["file_name"]).exists()


def test_a_backup_the_node_no_longer_lists_is_marked_deleted(failed_migration, weather, node_client):
    send_report(node_client, weather, database=database_report(weather), backups=[])

    assert PluginDatabaseBackup.objects.get(pk=failed_migration.backup_id).deleted_at is not None


def test_a_report_without_the_database_section_says_nothing_about_backups(failed_migration, weather, node_client):
    send_report(node_client, weather, backups=[])

    assert PluginDatabaseBackup.objects.get(pk=failed_migration.backup_id).deleted_at is None


def test_a_backup_listed_again_is_present_again(failed_migration, weather, node_client):
    body = backup_body(failed_migration)
    send_report(node_client, weather, database=database_report(weather), backups=[])

    send_report(node_client, weather, database=database_report(weather), backups=[body])

    assert PluginDatabaseBackup.objects.get(pk=failed_migration.backup_id).deleted_at is None


def test_a_file_whose_digest_changed_is_marked_and_never_restorable(failed_migration, weather, node_client, superadmin_client, log_messages):
    changed = {**backup_body(failed_migration), "sha256": "c" * 64}

    send_report(node_client, weather, database=database_report(weather), backups=[changed])

    backup = PluginDatabaseBackup.objects.get(pk=failed_migration.backup_id)
    assert (backup.sha256_mismatch, backup.sha256) == (True, "e" * 64)
    [listed] = superadmin_client.get("/api/admin/plugins/weather/backups/").json()["backups"]
    assert (listed["restorable"], listed["not_restorable_reason"]) == (False, "mismatch")
    assert any(message.startswith("plugins.backup.mismatch ") for message in log_messages)


def test_recording_known_backups_costs_the_same_however_many_there_are(failed_migration, weather, node_client, database):
    def queries_of_report(backups):
        send_report(node_client, weather, database=database_report(weather), backups=backups)
        with CaptureQueriesContext(connection) as captured:
            send_report(node_client, weather, database=database_report(weather), backups=backups)
        return len(captured.captured_queries)

    one = [backup_body(failed_migration)]
    with_one = queries_of_report(one)
    several = one + [
        backup_body(failed_migration, reason="pre_restore", taken_at=NOW - timedelta(minutes=minutes))
        for minutes in range(1, 5)
    ]

    assert queries_of_report(several) == with_one


# ---- retention ----


def test_the_newest_pre_upgrade_backups_within_the_grace_period_are_kept(database, settings):
    settings.PLUGINS_GRACE_PERIOD_DAYS = 30
    backups = [_backup(database, days_ago=days, pk_offset=index + 1) for index, days in enumerate([1, 2, 3, 4, 40])]

    to_delete = backup_retention(backups, open_upgrade_id=None, restoring_backup_id=None, now=NOW)

    assert BACKUPS_KEPT == 3
    assert to_delete == [backups[4].file_name, backups[3].file_name]


def test_the_open_upgrade_s_backups_and_an_open_restore_s_backup_are_pinned(database, failed_migration, settings):
    settings.PLUGINS_GRACE_PERIOD_DAYS = 30
    pinned = failed_migration.backup
    restore_backup = _backup(database, upgrade=failed_migration, reason="pre_restore", days_ago=50)
    restoring = _backup(database, days_ago=60, pk_offset=7)
    closed_restore = _backup(database, reason="pre_restore", days_ago=1, pk_offset=8)
    # With the open upgrade's own, these make the three newest pre-upgrade backups.
    recent = [_backup(database, days_ago=days, pk_offset=10 + days) for days in (1, 2)]

    to_delete = backup_retention(
        [pinned, restore_backup, restoring, closed_restore, *recent],
        open_upgrade_id=failed_migration.pk,
        restoring_backup_id=restoring.pk,
        now=NOW,
    )

    assert to_delete == [closed_restore.file_name]


def test_the_desired_state_lists_the_backups_to_delete(database, weather, node_client, settings):
    settings.PLUGINS_GRACE_PERIOD_DAYS = 30
    old = _backup(database, days_ago=400)

    placement = node_client.get("/api/plugin-nodes/self/desired-state/").json()["placements"][0]

    assert placement["backups_to_delete"] == [old.file_name]


# ---- the list ----


def test_the_list_shows_present_backups_newest_first_with_what_can_be_restored(
    database, failed_migration, superadmin_client
):
    earlier = _backup(database, days_ago=5, pk_offset=3)
    _backup(database, days_ago=6, pk_offset=4, deleted_at=NOW)

    body = superadmin_client.get("/api/admin/plugins/weather/backups/").json()

    assert body["verification_phrase"] == "restore-weather"
    assert [(row["id"], row["restorable"], row["not_restorable_reason"]) for row in body["backups"]] == [
        (failed_migration.backup_id, True, None),
        (earlier.pk, False, "earlier_upgrade"),
    ]
    assert body["backups"][0]["upgrade"] == {"id": failed_migration.pk, "to_version": "0.7.0"}


def test_the_open_upgrade_s_backup_cannot_be_restored_before_a_migration_failed(failed_migration, superadmin_client):
    PluginUpgrade.objects.filter(pk=failed_migration.pk).update(failed_at=None)

    [row] = superadmin_client.get("/api/admin/plugins/weather/backups/").json()["backups"]

    assert (row["restorable"], row["not_restorable_reason"]) == (False, "not_now")


def test_a_plugin_without_a_database_lists_no_backups(running_plugin, superadmin_client):
    running_plugin()

    response = superadmin_client.get("/api/admin/plugins/weather/backups/")

    assert response.status_code == 200
    assert response.json() == {"verification_phrase": "restore-weather", "backups": []}


def test_an_unknown_plugin_has_no_backup_list(superadmin_client):
    assert superadmin_client.get("/api/admin/plugins/missing/backups/").json()["code"] == "plugin_not_found"
