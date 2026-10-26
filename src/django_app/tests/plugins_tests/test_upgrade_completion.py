"""The node's reports during an upgrade: its progress, its failures, and the upgrade's completion."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from plugins.lifecycle.upgrade_service import PluginUpgradeService
from plugins.models import (
    ActivityAction,
    GrantState,
    HookJobKind,
    HookJobState,
    Plugin,
    PluginActivityEvent,
    PluginGrant,
    PluginHookJob,
    PluginPackage,
    PluginPlacement,
    PluginState,
    PluginUpgrade,
    ReviewState,
    UpgradeStage,
)
from plugins.packages.spa_publisher import CURRENT_LINK, MAINTENANCE_FLAG

from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    SECOND_MIGRATION,
    SECOND_MIGRATION_SQL,
    active_grant,
    advance_url,
    backup_body,
    database_report,
    ledger_of,
    newer,
    placement_of,
    send_report,
    upgrade_jobs,
    upgrade_of,
    upgrade_report,
    weather,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]


@pytest.fixture
def migrating(weather, newer, upgrade_of, node_client, django_capture_on_commit_callbacks):
    """Factory → an upgrade of Weather to 0.7.0 (with an upgrade hook) in its migrating stage."""

    def _make(**changes):
        upgrade = upgrade_of(newer(name="Weather Pro", hooks={"upgrade": True}, **changes))
        with django_capture_on_commit_callbacks(execute=True):
            assert node_client.post(advance_url(upgrade.pk), {"to": "maintenance"}, format="json").status_code == 204
        body = {"to": "migrations", "backup": backup_body(upgrade)}
        assert node_client.post(advance_url(upgrade.pk), body, format="json").status_code == 204
        upgrade.refresh_from_db()
        return upgrade

    return _make


def _target_running(node_client, plugin, capture, **observed):
    with capture(execute=True):
        send_report(node_client, plugin, observed_version="0.7.0", **observed)


def test_a_healthy_target_completes_the_upgrade(
    migrating, weather, node_client, spa_root, package_store, django_capture_on_commit_callbacks, log_messages
):
    upgrade = migrating()
    previous = PluginPackage.objects.get(pk=weather.current_package_id)
    previous_key = previous.storage_key

    _target_running(node_client, weather, django_capture_on_commit_callbacks)

    upgrade.refresh_from_db()
    plugin = Plugin.objects.get(pk=weather.pk)
    assert (upgrade.stage, upgrade.finished_at is not None) == (UpgradeStage.DONE, True)
    assert (plugin.state, plugin.current_package_id, plugin.name) == (PluginState.RUNNING, upgrade.to_package_id, "Weather Pro")
    assert (spa_root / "weather" / CURRENT_LINK).readlink().name == "0.7.0"
    assert not (spa_root / "weather" / MAINTENANCE_FLAG).exists()
    assert not (spa_root / "weather" / "0.6.0").exists()
    assert not PluginPackage.objects.filter(pk=previous.pk).exists()
    assert previous_key not in package_store.objects
    event = PluginActivityEvent.objects.get(action=ActivityAction.PLUGIN_UPGRADED)
    assert (event.detail["from_version"], event.detail["to_version"]) == ("0.6.0", "0.7.0")
    assert event.detail["maintenance_seconds"] >= 0
    assert any(message.startswith("plugins.upgrade.done ") for message in log_messages)


def test_a_pending_package_survives_the_completion(migrating, weather, newer, node_client, django_capture_on_commit_callbacks):
    upgrade = migrating()
    pending = newer("0.8.0")

    _target_running(node_client, weather, django_capture_on_commit_callbacks)

    assert PluginPackage.objects.get(pk=pending.pk).review_state == ReviewState.PENDING
    assert PluginPackage.objects.filter(plugin=weather).count() == 2
    assert upgrade.to_package_id in PluginPackage.objects.values_list("pk", flat=True)


def test_completion_brings_each_organization_to_the_new_version(
    migrating, weather, node_client, superadmin, acme, beta, django_capture_on_commit_callbacks
):
    from rbac.models import Organization

    behind = active_grant(weather, acme, superadmin)
    failed = active_grant(weather, beta, superadmin)
    PluginGrant.objects.filter(pk=failed.pk).update(state=GrantState.UPGRADE_FAILED)
    left_alone = {
        state: PluginGrant.objects.create(
            plugin=weather,
            org=Organization.objects.create(name=f"Org {state}"),
            state=state,
            installed_version="0.6.0",
            created_by=superadmin,
        )
        for state in (GrantState.GRANTING, GrantState.INSTALL_FAILED, GrantState.SUSPENDED)
    }
    upgrade = migrating()

    _target_running(node_client, weather, django_capture_on_commit_callbacks)

    for grant in (behind, failed):
        grant.refresh_from_db()
        assert grant.state == GrantState.UPGRADING
        [job] = upgrade_jobs(grant)
        assert (job.state, job.package_id, job.failures_in_series) == (HookJobState.PENDING, upgrade.to_package_id, 0)
    for state, grant in left_alone.items():
        grant.refresh_from_db()
        assert grant.state == state
        assert not upgrade_jobs(grant).exists()


def test_without_an_upgrade_hook_organizations_are_active_on_the_new_version(
    weather, newer, upgrade_of, node_client, superadmin, acme, django_capture_on_commit_callbacks
):
    grant = active_grant(weather, acme, superadmin)
    upgrade = upgrade_of(newer())
    with django_capture_on_commit_callbacks(execute=True):
        node_client.post(advance_url(upgrade.pk), {"to": "maintenance"}, format="json")
    node_client.post(advance_url(upgrade.pk), {"to": "migrations", "backup": backup_body(upgrade)}, format="json")

    _target_running(node_client, weather, django_capture_on_commit_callbacks)

    grant.refresh_from_db()
    assert (grant.state, grant.installed_version) == (GrantState.ACTIVE, "0.7.0")
    assert not upgrade_jobs(grant).exists()


def test_a_stale_report_does_not_complete(migrating, weather, node_client, django_capture_on_commit_callbacks):
    upgrade = migrating()
    generation = placement_of(weather).restart_generation
    PluginPlacement.objects.filter(plugin=weather).update(restart_generation=generation + 1)

    _target_running(node_client, weather, django_capture_on_commit_callbacks, applied_restart_generation=generation)

    upgrade.refresh_from_db()
    assert upgrade.stage == UpgradeStage.MIGRATING


def test_the_old_version_reported_healthy_neither_completes_nor_moves_maintenance(migrating, weather, node_client):
    upgrade = migrating()

    send_report(node_client, weather, observed_version="0.6.0")

    upgrade.refresh_from_db()
    assert upgrade.stage == UpgradeStage.MIGRATING
    assert Plugin.objects.get(pk=weather.pk).state == PluginState.MAINTENANCE


def test_a_failure_report_fails_the_upgrade_once(migrating, weather, node_client, log_messages):
    upgrade = migrating()
    failed = upgrade_report(upgrade, state="failed", step="migrate", last_error="004_broken.sql line 1: [22012] division by zero")

    send_report(node_client, weather, observed_state="stopped", health="unknown", upgrade=failed)
    send_report(node_client, weather, observed_state="stopped", health="unknown", upgrade=failed)

    upgrade.refresh_from_db()
    assert (upgrade.failed, upgrade.step, upgrade.last_error) == (True, "migrate", failed["last_error"])
    events = PluginActivityEvent.objects.filter(action=ActivityAction.PLUGIN_UPGRADE_FAILED)
    assert [event.detail for event in events] == [
        {"to_version": "0.7.0", "stage": "migrating", "step": "migrate", "error": failed["last_error"]}
    ]
    assert not any("division by zero" in message for message in log_messages)


def test_a_working_report_records_the_step(migrating, weather, node_client):
    upgrade = migrating()

    send_report(node_client, weather, observed_state="stopped", health="unknown", upgrade=upgrade_report(upgrade, step="migrate"))

    upgrade.refresh_from_db()
    assert (upgrade.step, upgrade.failed) == ("migrate", False)


@pytest.mark.parametrize("change", [{"generation": 99}, {"stage": "maintenance"}])
def test_a_report_for_another_generation_or_stage_is_ignored(migrating, weather, node_client, change):
    upgrade = migrating()

    send_report(
        node_client,
        weather,
        observed_state="stopped",
        health="unknown",
        upgrade=upgrade_report(upgrade, state="failed", step="migrate", **change),
    )

    upgrade.refresh_from_db()
    assert upgrade.failed is False


def test_a_target_that_fails_to_start_fails_the_upgrade_at_start(migrating, weather, node_client):
    upgrade = migrating()

    send_report(node_client, weather, observed_state="failed", observed_version="0.7.0", health="failing", last_error="Traceback: ImportError")

    upgrade.refresh_from_db()
    assert (upgrade.failed, upgrade.step, upgrade.last_error) == (True, "start", "Traceback: ImportError")
    assert Plugin.objects.get(pk=weather.pk).state == PluginState.MAINTENANCE


def test_a_retry_clears_the_failure_and_restarts_the_stage(migrating, weather, node_client, superadmin):
    upgrade = migrating()
    send_report(node_client, weather, observed_state="stopped", health="unknown", upgrade=upgrade_report(upgrade, state="failed", step="migrate", last_error="boom"))
    generation = placement_of(weather).restart_generation

    PluginUpgradeService().retry("weather", superadmin)

    upgrade.refresh_from_db()
    assert (upgrade.failed, upgrade.step, upgrade.last_error) == (False, None, None)
    assert placement_of(weather).restart_generation == generation + 1
    assert PluginActivityEvent.objects.get(action=ActivityAction.PLUGIN_UPGRADE_RETRIED).detail == {"to_version": "0.7.0"}


def test_a_failed_report_sent_before_the_node_saw_the_retry_does_not_fail_it_again(migrating, weather, node_client, superadmin):
    upgrade = migrating()
    stale = upgrade_report(upgrade, state="failed", step="migrate", last_error="boom")
    send_report(node_client, weather, observed_state="stopped", health="unknown", upgrade=stale)
    PluginUpgradeService().retry("weather", superadmin)

    send_report(node_client, weather, observed_state="stopped", health="unknown", applied_restart_generation=None, upgrade=stale)

    upgrade.refresh_from_db()
    assert upgrade.failed is False


def test_while_an_upgrade_is_open_a_failed_process_does_not_fail_the_plugin(weather, newer, upgrade_of, node_client):
    upgrade_of(newer())

    send_report(node_client, weather, observed_state="failed", health="failing")

    assert Plugin.objects.get(pk=weather.pk).state == PluginState.RUNNING


def test_the_ledger_is_stored_from_a_failed_migration_report(migrating, weather, node_client):
    from plugins.models import PluginDatabase

    upgrade = migrating()
    ledger = ledger_of(weather.current_package, ("002_conditions.sql", SECOND_MIGRATION_SQL))

    send_report(node_client, weather, observed_state="stopped", health="unknown", database=database_report(weather, state="failed", ledger=ledger, last_error="boom"))

    assert PluginDatabase.objects.get(plugin=weather).ledger == ledger
    assert upgrade.pk


def test_the_follow_up_locks_the_plugin_first_after_the_observations_commit(migrating, weather, node_client):
    migrating()

    with CaptureQueriesContext(connection) as captured:
        send_report(node_client, weather, observed_state="stopped", health="unknown")

    locks = [
        query["sql"].split(" FROM ", 1)[1].split(" ", 1)[0]
        for query in captured.captured_queries
        if " FOR UPDATE" in query["sql"] or " FOR NO KEY UPDATE" in query["sql"]
    ]
    first_plugin = locks.index('"plugins_plugin"')
    assert locks[0] == '"plugins_pluginplacement"'
    assert '"plugins_plugin"' not in locks[:first_plugin]
    assert locks[first_plugin + 1] == '"plugins_pluginupgrade"'
    plugin_lock = next(query["sql"] for query in captured.captured_queries if ' FROM "plugins_plugin" ' in query["sql"] and "UPDATE" in query["sql"])
    assert "FOR NO KEY UPDATE" in plugin_lock and "SKIP LOCKED" in plugin_lock


def test_a_hook_job_left_from_before_is_given_a_fresh_series_by_the_new_version(
    migrating, weather, node_client, superadmin, acme, django_capture_on_commit_callbacks
):
    grant = active_grant(weather, acme, superadmin, version="0.5.0")
    PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.UPGRADING)
    job = PluginHookJob.objects.create(
        plugin=weather,
        grant=grant,
        organization_id=acme.pk,
        organization_name=acme.name,
        kind=HookJobKind.UPGRADE,
        package=weather.current_package,
        timeout_seconds=60,
        failures_in_series=2,
        next_attempt_at="2099-01-01T00:00:00Z",
    )
    migrating()

    _target_running(node_client, weather, django_capture_on_commit_callbacks)

    job.refresh_from_db()
    assert (job.failures_in_series, job.next_attempt_at) == (0, None)
    assert upgrade_jobs(grant).count() == 1


def test_nothing_happens_to_an_upgrade_that_is_over(migrating, weather, node_client, superadmin, django_capture_on_commit_callbacks):
    upgrade = migrating()
    _target_running(node_client, weather, django_capture_on_commit_callbacks)

    send_report(
        node_client,
        weather,
        observed_state="stopped",
        health="unknown",
        upgrade=upgrade_report(upgrade, state="failed", stage="migrating"),
    )

    upgrade.refresh_from_db()
    assert (upgrade.stage, upgrade.failed) == (UpgradeStage.DONE, False)
    assert PluginUpgrade.objects.filter(plugin=weather).count() == 1


def test_the_desired_state_says_the_stage_failed_until_a_retry(migrating, weather, node_client, superadmin):
    upgrade = migrating()
    desired_url = "/api/plugin-nodes/self/desired-state/"
    assert node_client.get(desired_url).json()["placements"][0]["upgrade"]["failed"] is False

    send_report(
        node_client,
        weather,
        observed_state="stopped",
        health="unknown",
        upgrade=upgrade_report(upgrade, state="failed", step="migrate", last_error="boom"),
    )
    failed = node_client.get(desired_url).json()["placements"][0]["upgrade"]
    PluginUpgradeService().retry("weather", superadmin)
    retried = node_client.get(desired_url).json()["placements"][0]

    assert failed["failed"] is True
    assert retried["upgrade"]["failed"] is False
    assert retried["restart_generation"] == placement_of(weather).restart_generation
