"""Whether the database holds a change of the upgrade is judged against the ledger as it was when
the node first asked to run the upgrade's migrations, so a file an earlier version dropped but the
database still lists is no change."""

import pytest
from plugins.models import PluginDatabase, PluginUpgrade

from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    advance_url,
    backup_body,
    baseline_of,
    digest,
    ledger_of,
    newer,
    upgrade_of,
    weather,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PLUGIN_URL = "/api/admin/plugins/weather/"
DROPPED = ("002_dropped.sql", b"CREATE TABLE dropped (id bigint);\n")
NEW_MIGRATION = "database/migrations/003_conditions.sql"
NEW_MIGRATION_SQL = b"CREATE TABLE conditions (id bigint PRIMARY KEY);\n"


@pytest.fixture
def ledger_with_a_dropped_file(weather):
    """Weather 0.6.0's database lists a file no installed version has any more."""
    ledger = ledger_of(weather.current_package, DROPPED)
    PluginDatabase.objects.filter(plugin=weather).update(ledger=ledger)
    return ledger


def _to_migrating(node_client, upgrade, capture):
    with capture(execute=True):
        assert node_client.post(advance_url(upgrade.pk), {"to": "maintenance"}, format="json").status_code == 204
    body = {"to": "migrations", "backup": backup_body(upgrade)}
    assert node_client.post(advance_url(upgrade.pk), body, format="json").status_code == 204
    PluginUpgrade.objects.filter(pk=upgrade.pk).update(failed_at=upgrade.started_at, step="migrate")
    upgrade.refresh_from_db()
    return upgrade


@pytest.fixture
def failed_first_migration(
    ledger_with_a_dropped_file, newer, upgrade_of, node_client, django_capture_on_commit_callbacks
):
    upgrade = upgrade_of(newer(migrations={NEW_MIGRATION: NEW_MIGRATION_SQL}))
    return _to_migrating(node_client, upgrade, django_capture_on_commit_callbacks)


def _detail(client):
    return client.get(PLUGIN_URL).json()


def test_the_ledger_is_kept_on_the_upgrade_when_the_migrations_are_first_asked_for(
    failed_first_migration, ledger_with_a_dropped_file
):
    assert failed_first_migration.ledger_at_migrations == ledger_with_a_dropped_file


def test_a_file_an_earlier_version_dropped_is_no_change_and_the_upgrade_can_be_cancelled(
    failed_first_migration, superadmin_client
):
    detail = _detail(superadmin_client)
    assert detail["open_upgrade"]["database_changed"] is False
    assert "cancel_upgrade" in detail["allowed_actions"]
    assert superadmin_client.post(f"{PLUGIN_URL}upgrade/cancel/").status_code == 200


def test_a_migration_of_the_new_version_in_the_ledger_is_a_change(
    failed_first_migration, ledger_with_a_dropped_file, superadmin_client
):
    PluginDatabase.objects.filter(plugin=failed_first_migration.plugin).update(
        ledger=[*ledger_with_a_dropped_file, {"name": "003_conditions.sql", "sha256": digest(NEW_MIGRATION_SQL)}]
    )

    assert _detail(superadmin_client)["open_upgrade"]["database_changed"] is True
    assert superadmin_client.post(f"{PLUGIN_URL}upgrade/cancel/").json()["code"] == "upgrade_not_cancellable"


def test_an_upgrade_opened_before_the_snapshot_was_kept_is_compared_with_the_version_it_upgrades_from(
    failed_first_migration, superadmin_client
):
    PluginUpgrade.objects.filter(pk=failed_first_migration.pk).update(ledger_at_migrations=None)

    # The dropped file is not in 0.6.0's package: counted as a change, as before the snapshot.
    assert _detail(superadmin_client)["open_upgrade"]["database_changed"] is True


def test_a_newer_target_replacing_a_failed_one_keeps_the_first_snapshot(
    failed_first_migration,
    ledger_with_a_dropped_file,
    newer,
    superadmin_client,
    node_client,
    django_capture_on_commit_callbacks,
):
    weather = failed_first_migration.plugin
    left_by_the_failed_target = [
        *ledger_with_a_dropped_file,
        {"name": "003_conditions.sql", "sha256": digest(NEW_MIGRATION_SQL)},
    ]
    PluginDatabase.objects.filter(plugin=weather).update(ledger=left_by_the_failed_target)
    replacement = newer("0.8.0", migrations={NEW_MIGRATION: NEW_MIGRATION_SQL})
    approval = superadmin_client.post(
        f"/api/admin/plugins/packages/{replacement.pk}/approve/",
        {
            "untrusted_acknowledged": True,
            "access_growth_acknowledged": True,
            "reviewed_against_package_id": baseline_of(weather).pk,
        },
        format="json",
    )
    assert approval.status_code == 202, approval.content
    upgrade = PluginUpgrade.objects.get(pk=failed_first_migration.pk)
    assert upgrade.stage == "maintenance"

    body = {"to": "migrations", "backup": backup_body(upgrade)}
    assert node_client.post(advance_url(upgrade.pk), body, format="json").status_code == 204

    upgrade.refresh_from_db()
    assert upgrade.ledger_at_migrations == ledger_with_a_dropped_file
    assert _detail(superadmin_client)["open_upgrade"]["database_changed"] is True


def test_before_the_first_migration_run_nothing_has_changed(
    ledger_with_a_dropped_file, newer, upgrade_of, superadmin_client
):
    upgrade_of(newer(migrations={NEW_MIGRATION: NEW_MIGRATION_SQL}))

    assert _detail(superadmin_client)["open_upgrade"]["database_changed"] is False
