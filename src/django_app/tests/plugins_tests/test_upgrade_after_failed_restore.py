"""After a restore that failed once it may have changed the database, only another restore or
the plugin's deletion is allowed: Cancel, Retry and a newer version would run against a database
that may be empty."""

import pytest
from plugins.models import PluginDatabase, PluginDatabaseRestore, PluginUpgrade

from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    SECOND_MIGRATION_SQL,
    TAKEN_AT,
    advance_url,
    backup_body,
    baseline_of,
    database_report,
    ledger_of,
    newer,
    send_report,
    upgrade_of,
    weather,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PLUGIN_URL = "/api/admin/plugins/weather/"
PHRASE = {"verification_phrase": "restore-weather"}
CHANGING_STEPS = ["recreate", "restore", "settings", "assert"]
ONLY_RESTORE_AND_PURGE = ["restore_backup", "purge"]


@pytest.fixture
def first_migration_failed(weather, newer, upgrade_of, node_client, django_capture_on_commit_callbacks):
    """Weather's upgrade to 0.7.0 failed at its first new migration: the ledger holds 0.6.0's files."""
    upgrade = upgrade_of(newer())
    with django_capture_on_commit_callbacks(execute=True):
        node_client.post(advance_url(upgrade.pk), {"to": "maintenance"}, format="json")
    node_client.post(advance_url(upgrade.pk), {"to": "migrations", "backup": backup_body(upgrade)}, format="json")
    PluginUpgrade.objects.filter(pk=upgrade.pk).update(failed_at=upgrade.started_at, step="migrate", last_error="boom")
    upgrade.refresh_from_db()
    return upgrade


def _restore(client, upgrade):
    response = client.post(f"{PLUGIN_URL}backups/{upgrade.backup_id}/restore/", PHRASE, format="json")
    assert response.status_code == 202, response.content
    return PluginDatabaseRestore.objects.order_by("-pk").first()


def _restore_ends(node_client, weather, restore, *, state, step, **observed):
    send_report(
        node_client,
        weather,
        observed_state="stopped",
        health="unknown",
        restore={"restore_id": restore.pk, "state": state, "step": step, "last_error": None if state == "succeeded" else "boom"},
        **observed,
    )


def _approve(client, package):
    return client.post(
        f"/api/admin/plugins/packages/{package.pk}/approve/",
        {
            "untrusted_acknowledged": True,
            "access_growth_acknowledged": True,
            "reviewed_against_package_id": baseline_of(package.plugin).pk,
        },
        format="json",
    )


def _allowed(client):
    return client.get(PLUGIN_URL).json()["allowed_actions"]


def _assert_only_restore_and_purge(client, newer_package):
    assert _allowed(client) == ONLY_RESTORE_AND_PURGE
    cancel = client.post(f"{PLUGIN_URL}upgrade/cancel/")
    assert (cancel.status_code, cancel.json()["code"]) == (409, "upgrade_not_cancellable")
    retry = client.post(f"{PLUGIN_URL}upgrade/retry/")
    assert (retry.status_code, retry.json()["code"]) == (409, "upgrade_not_retryable")
    approval = _approve(client, newer_package)
    assert (approval.status_code, approval.json()["code"]) == (409, "plugin_not_upgradable")


@pytest.mark.parametrize("step", CHANGING_STEPS)
def test_a_restore_that_succeeded_then_one_that_failed_after_changing_the_database_leaves_only_restore_and_purge(
    first_migration_failed, weather, newer, superadmin_client, node_client, step
):
    first = _restore(superadmin_client, first_migration_failed)
    _restore_ends(
        node_client,
        weather,
        first,
        state="succeeded",
        step="assert",
        database=database_report(weather, ledger=ledger_of(weather.current_package)),
    )
    assert "cancel_upgrade" in _allowed(superadmin_client)
    second = _restore(superadmin_client, first_migration_failed)

    _restore_ends(node_client, weather, second, state="failed", step=step)

    _assert_only_restore_and_purge(superadmin_client, newer("0.8.0"))


@pytest.mark.parametrize("step", CHANGING_STEPS)
def test_a_failed_first_migration_then_a_failed_restore_leaves_only_restore_and_purge(
    first_migration_failed, weather, newer, superadmin_client, node_client, step
):
    assert "cancel_upgrade" in _allowed(superadmin_client)
    restore = _restore(superadmin_client, first_migration_failed)

    _restore_ends(node_client, weather, restore, state="failed", step=step)

    _assert_only_restore_and_purge(superadmin_client, newer("0.8.0"))


def test_another_restore_can_still_be_asked_for_and_its_success_brings_the_rules_back(
    first_migration_failed, weather, superadmin_client, node_client
):
    failed = _restore(superadmin_client, first_migration_failed)
    _restore_ends(node_client, weather, failed, state="failed", step="recreate")

    again = _restore(superadmin_client, first_migration_failed)
    _restore_ends(
        node_client,
        weather,
        again,
        state="succeeded",
        step="assert",
        database=database_report(weather, ledger=ledger_of(weather.current_package)),
    )

    assert {"cancel_upgrade", "retry_upgrade", "restore_backup", "purge"} <= set(_allowed(superadmin_client))


@pytest.mark.parametrize("step", ["verify", "backup", "close"])
def test_a_restore_that_failed_before_recreating_the_database_leaves_the_rules_as_they_were(
    first_migration_failed, weather, newer, superadmin_client, node_client, step
):
    newer_package = newer("0.8.0")
    restore = _restore(superadmin_client, first_migration_failed)

    _restore_ends(node_client, weather, restore, state="failed", step=step)

    assert _allowed(superadmin_client) == ["upgrade", "cancel_upgrade", "retry_upgrade", "restore_backup", "purge"]
    assert _approve(superadmin_client, newer_package).status_code == 202


def test_a_failed_restore_of_an_earlier_upgrade_does_not_hold_back_the_open_one(
    first_migration_failed, weather, superadmin_client, node_client
):
    restore = _restore(superadmin_client, first_migration_failed)
    _restore_ends(node_client, weather, restore, state="failed", step="recreate")
    # As if the failed restore belonged to an upgrade that is over: this one has none.
    earlier = PluginUpgrade.objects.create(
        plugin=weather, from_version="0.5.0", to_version="0.6.0", stage="done", started_at=TAKEN_AT
    )
    PluginDatabaseRestore.objects.filter(pk=restore.pk).update(upgrade=earlier)

    assert "cancel_upgrade" in _allowed(superadmin_client)


def test_a_migration_that_changed_the_database_and_a_failed_restore_still_allow_a_restore(
    first_migration_failed, weather, superadmin_client, node_client
):
    PluginDatabase.objects.filter(plugin=weather).update(
        ledger=ledger_of(weather.current_package, ("002_conditions.sql", SECOND_MIGRATION_SQL))
    )
    restore = _restore(superadmin_client, first_migration_failed)

    _restore_ends(node_client, weather, restore, state="failed", step="restore")

    assert _allowed(superadmin_client) == ONLY_RESTORE_AND_PURGE
    assert superadmin_client.post(f"{PLUGIN_URL}backups/{first_migration_failed.backup_id}/restore/", PHRASE, format="json").status_code == 202
