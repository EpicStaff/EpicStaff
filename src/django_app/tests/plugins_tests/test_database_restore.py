"""Restoring a backup into a plugin's database during a failed upgrade."""

import pytest
from plugins.databases.restore_service import RESTORED_MESSAGE
from plugins.models import (
    ActivityAction,
    PluginActivityEvent,
    PluginDatabase,
    PluginDatabaseBackup,
    PluginDatabaseRestore,
    PluginUpgrade,
    RestoreState,
)

from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    SECOND_MIGRATION_SQL,
    TAKEN_AT,
    advance_url,
    backup_body,
    database_report,
    ledger_of,
    newer,
    send_report,
    upgrade_of,
    weather,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PHRASE = {"verification_phrase": "restore-weather"}


@pytest.fixture
def failed_migration(weather, newer, upgrade_of, node_client, django_capture_on_commit_callbacks):
    upgrade = upgrade_of(newer())
    with django_capture_on_commit_callbacks(execute=True):
        node_client.post(advance_url(upgrade.pk), {"to": "maintenance"}, format="json")
    node_client.post(advance_url(upgrade.pk), {"to": "migrations", "backup": backup_body(upgrade)}, format="json")
    PluginUpgrade.objects.filter(pk=upgrade.pk).update(failed_at=upgrade.started_at, step="migrate", last_error="boom")
    PluginDatabase.objects.filter(plugin=weather).update(
        ledger=ledger_of(weather.current_package, ("002_conditions.sql", SECOND_MIGRATION_SQL))
    )
    upgrade.refresh_from_db()
    return upgrade


def _restore(client, backup_id, body=PHRASE, identifier="weather"):
    return client.post(f"/api/admin/plugins/{identifier}/backups/{backup_id}/restore/", body, format="json")


def _nothing_written():
    return not PluginDatabaseRestore.objects.exists() and not PluginActivityEvent.objects.filter(
        action=ActivityAction.DATABASE_RESTORE_REQUESTED
    ).exists()


def test_a_restore_of_the_failed_upgrade_s_backup_is_asked_of_the_node(
    failed_migration, superadmin_client, node_client, log_messages, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _restore(superadmin_client, failed_migration.backup_id)

    assert response.status_code == 202, response.content
    body = response.json()
    assert (body["state"], body["backup"]["id"], body["backup"]["reason"]) == ("pending", failed_migration.backup_id, "pre_upgrade")
    restore = PluginDatabaseRestore.objects.get()
    placement = node_client.get("/api/plugin-nodes/self/desired-state/").json()["placements"][0]
    assert placement["restore"] == {
        "restore_id": restore.pk,
        "upgrade_id": failed_migration.pk,
        "backup_file": failed_migration.backup.file_name,
        "backup_sha256": failed_migration.backup.sha256,
    }
    assert PluginActivityEvent.objects.get(action=ActivityAction.DATABASE_RESTORE_REQUESTED).detail == {
        "file_name": failed_migration.backup.file_name
    }
    detail = superadmin_client.get("/api/admin/plugins/weather/").json()
    assert detail["allowed_actions"] == []
    assert any(message.startswith("plugins.restore.requested ") for message in log_messages)
    assert not any("restore-weather" in message for message in log_messages)


def test_an_unknown_plugin_comes_before_everything(superadmin_client):
    response = _restore(superadmin_client, 1, identifier="missing")

    assert (response.status_code, response.json()["code"]) == (404, "plugin_not_found")


@pytest.mark.parametrize("which", ["unknown", "other_plugin", "deleted"])
def test_a_backup_the_plugin_does_not_hold_is_not_found_even_with_a_wrong_phrase(
    failed_migration, superadmin_client, database_plugin, which
):
    backup_id = failed_migration.backup_id
    if which == "unknown":
        backup_id = 999999
    elif which == "other_plugin":
        other = database_plugin(id="tides")
        backup_id = PluginDatabaseBackup.objects.create(
            plugin_database=PluginDatabase.objects.get(plugin=other),
            file_name="20261021T101500Z-u1-pre_upgrade.dump",
            reason="pre_upgrade",
            version="0.2.0",
            size_bytes=1,
            sha256="a" * 64,
            created_at=TAKEN_AT,
        ).pk
    else:
        PluginDatabaseBackup.objects.filter(pk=backup_id).update(deleted_at=TAKEN_AT)

    response = _restore(superadmin_client, backup_id, {"verification_phrase": "wrong"})

    assert (response.status_code, response.json()["code"]) == (404, "backup_not_found")
    assert _nothing_written()


@pytest.mark.parametrize("why", ["not_failed", "preparing_stage", "earlier_upgrade", "mismatch"])
def test_a_restore_outside_the_rule_conflicts_before_the_phrase_is_read(failed_migration, superadmin_client, why):
    backup = failed_migration.backup
    if why == "not_failed":
        PluginUpgrade.objects.filter(pk=failed_migration.pk).update(failed_at=None)
    elif why == "preparing_stage":
        PluginUpgrade.objects.filter(pk=failed_migration.pk).update(stage="maintenance")
    elif why == "earlier_upgrade":
        PluginDatabaseBackup.objects.filter(pk=backup.pk).update(upgrade=None)
    else:
        PluginDatabaseBackup.objects.filter(pk=backup.pk).update(sha256_mismatch=True)

    response = _restore(superadmin_client, backup.pk, {"verification_phrase": "wrong"})

    assert (response.status_code, response.json()["code"]) == (409, "restore_not_allowed")
    assert _nothing_written()


@pytest.mark.parametrize("body", [{}, {"verification_phrase": "restore-Weather"}, {"verification_phrase": " restore-weather"}])
def test_a_missing_or_different_phrase_is_refused(failed_migration, superadmin_client, body):
    response = _restore(superadmin_client, failed_migration.backup_id, body)

    assert (response.status_code, response.json()["code"]) == (400, "invalid_restore_phrase")
    assert _nothing_written()


def test_a_phrase_that_is_not_text_is_refused_without_echoing_it(failed_migration, superadmin_client):
    response = _restore(superadmin_client, failed_migration.backup_id, {"verification_phrase": ["restore-weather"]})

    assert (response.status_code, response.json()["code"]) == (400, "invalid")
    assert "restore-weather" not in response.content.decode()
    assert _nothing_written()


def test_one_restore_at_a_time(failed_migration, superadmin_client):
    assert _restore(superadmin_client, failed_migration.backup_id).status_code == 202

    response = _restore(superadmin_client, failed_migration.backup_id)

    assert (response.status_code, response.json()["code"]) == (409, "restore_not_allowed")


def test_the_plugin_cannot_be_deleted_while_a_restore_runs(failed_migration, superadmin_client):
    _restore(superadmin_client, failed_migration.backup_id)

    response = superadmin_client.delete("/api/admin/plugins/weather/", {"verification_phrase": "purge-weather"}, format="json")

    assert (response.status_code, response.json()["code"]) == (409, "plugin_not_purgeable")


def test_a_running_report_records_the_step(failed_migration, weather, superadmin_client, node_client):
    _restore(superadmin_client, failed_migration.backup_id)
    restore = PluginDatabaseRestore.objects.get()

    send_report(node_client, weather, observed_state="stopped", health="unknown", restore={"restore_id": restore.pk, "state": "running", "step": "close"})

    restore.refresh_from_db()
    assert (restore.state, restore.step) == (RestoreState.RUNNING, "close")


def test_a_successful_restore_records_the_way_back_and_makes_cancel_possible(
    failed_migration, weather, superadmin_client, node_client
):
    _restore(superadmin_client, failed_migration.backup_id)
    restore = PluginDatabaseRestore.objects.get()
    pre_restore = backup_body(failed_migration, reason="pre_restore", taken_at=TAKEN_AT.replace(hour=11))
    restored_ledger = ledger_of(weather.current_package)

    send_report(
        node_client,
        weather,
        observed_state="stopped",
        health="unknown",
        database=database_report(weather, ledger=restored_ledger),
        backups=[backup_body(failed_migration), pre_restore],
        restore={
            "restore_id": restore.pk,
            "state": "succeeded",
            "step": "assert",
            "pre_restore_backup": pre_restore["file_name"],
        },
    )

    restore.refresh_from_db()
    failed_migration.refresh_from_db()
    assert restore.state == RestoreState.SUCCEEDED
    assert restore.pre_restore_backup.file_name == pre_restore["file_name"]
    assert failed_migration.failed is True
    assert failed_migration.last_error == RESTORED_MESSAGE.format(file_name=restore.backup_file_name)
    assert PluginDatabase.objects.get(plugin=weather).ledger == restored_ledger
    detail = superadmin_client.get("/api/admin/plugins/weather/").json()
    assert detail["open_upgrade"]["database_changed"] is False
    assert "cancel_upgrade" in detail["allowed_actions"]
    assert detail["open_upgrade"]["restore"]["state"] == "succeeded"
    assert PluginActivityEvent.objects.get(action=ActivityAction.DATABASE_RESTORED).detail == {
        "file_name": restore.backup_file_name,
        "pre_restore_file_name": pre_restore["file_name"],
    }
    assert node_client.get("/api/plugin-nodes/self/desired-state/").json()["placements"][0]["restore"] is None


def test_a_failed_restore_is_recorded_and_another_can_follow(failed_migration, weather, superadmin_client, node_client):
    _restore(superadmin_client, failed_migration.backup_id)
    restore = PluginDatabaseRestore.objects.get()

    send_report(
        node_client,
        weather,
        observed_state="stopped",
        health="unknown",
        restore={"restore_id": restore.pk, "state": "failed", "step": "restore", "last_error": "pg_restore exited 1"},
    )

    restore.refresh_from_db()
    assert (restore.state, restore.step, restore.last_error) == (RestoreState.FAILED, "restore", "pg_restore exited 1")
    assert PluginActivityEvent.objects.get(action=ActivityAction.DATABASE_RESTORE_FAILED).detail == {
        "step": "restore",
        "error": "pg_restore exited 1",
    }
    assert _restore(superadmin_client, failed_migration.backup_id).status_code == 202


def test_a_report_about_another_restore_changes_nothing(failed_migration, weather, superadmin_client, node_client):
    _restore(superadmin_client, failed_migration.backup_id)
    restore = PluginDatabaseRestore.objects.get()

    send_report(
        node_client,
        weather,
        observed_state="stopped",
        health="unknown",
        restore={"restore_id": restore.pk + 100, "state": "succeeded", "step": "assert"},
    )

    restore.refresh_from_db()
    assert restore.state == RestoreState.PENDING
