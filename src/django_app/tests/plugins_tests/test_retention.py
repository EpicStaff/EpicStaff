"""The scheduled maintenance: grace periods ending, deletions moving on, and the hourly sweep."""

import threading
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from plugins.lifecycle.grant_service import PluginGrantService
from plugins.lifecycle.housekeeping_service import (
    GRANT_DELETED_BEFORE_HOOK_FINISHED,
    REVOKED_KEY_RETENTION_DAYS,
    HousekeepingService,
)
from plugins.lifecycle.retention_service import RetentionService
from plugins.lifecycle.suspension_service import PluginSuspensionService
from plugins.models import (
    ActivityAction,
    GrantState,
    HookJobKind,
    HookJobState,
    Plugin,
    PluginActivityEvent,
    PluginGrant,
    PluginHookJob,
    PluginOwnedResource,
    PluginRolePermission,
    PluginServiceAccount,
    PluginServiceAccountKey,
    PluginState,
)
from tables.models import Session
from tables.services.session_manager_service import SessionManagerService

from tests.plugins_tests.suspension_helpers import flow, own, secret_row

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

START = datetime(2026, 10, 21, 12, 0, tzinfo=dt_timezone.utc)
HOOKS = {"install": False, "org_removed": True}


class Clock:
    def __init__(self):
        self.now = START


@pytest.fixture
def clock(monkeypatch):
    frozen = Clock()
    monkeypatch.setattr(timezone, "now", lambda: frozen.now)
    return frozen


@pytest.fixture(autouse=True)
def no_failed_rows_left():
    cache.delete_pattern("plugins:purge:failed:*")
    yield
    cache.delete_pattern("plugins:purge:failed:*")


@pytest.fixture
def stopped_sessions(monkeypatch):
    stopped = []
    monkeypatch.setattr(
        SessionManagerService().redis_service, "publish_stop_session", lambda session_id: stopped.append(session_id) or 1
    )
    return stopped


@pytest.fixture
def weather(weather_backend):
    return weather_backend(hooks=HOOKS)


@pytest.fixture
def suspended(weather, superadmin, acme, clock, settings):
    """Weather in Acme, suspended now with a 30-day grace period; it owns a secret there."""
    settings.PLUGINS_GRACE_PERIOD_DAYS = "30"
    grant = PluginGrantService().grant("weather", acme.pk, superadmin)
    own(secret_row(acme, "Weather · LLM key"), grant)
    PluginSuspensionService().suspend("weather", grant.pk, superadmin)
    return PluginGrant.objects.get(pk=grant.pk)


@pytest.fixture(autouse=True)
def no_stop_reaches_redis(monkeypatch):
    monkeypatch.setattr(SessionManagerService().redis_service, "publish_stop_session", lambda session_id: 1)


def _run(clock, **delta):
    """One tick at START + `delta`, with the callbacks its transactions leave for after commit."""
    clock.now = START + timedelta(**delta)
    with TestCase.captureOnCommitCallbacks(execute=True):
        return RetentionService().run()


# ---- a grace period ends ----


def test_nothing_happens_before_the_grace_period_ends(suspended, clock):
    report = _run(clock, days=30, seconds=-1)

    suspended.refresh_from_db()
    assert suspended.state == GrantState.SUSPENDED
    assert report.grants_expired == 0
    assert PluginOwnedResource.objects.count() == 1


def test_at_the_deadline_the_data_is_deleted_and_the_plugin_asked_to_delete_its_own(suspended, clock, acme, log_messages):
    report = _run(clock, days=30)

    suspended.refresh_from_db()
    assert (suspended.state, suspended.purge_started_at) == (GrantState.PURGING, clock.now)
    job = PluginHookJob.objects.get(kind=HookJobKind.ORG_REMOVED)
    assert (job.organization_id, job.organization_name, job.state) == (acme.pk, acme.name, HookJobState.PENDING)
    assert not PluginOwnedResource.objects.exists()
    assert (report.grants_expired, report.resources_purged, report.grants_purged) == (1, 1, 0)
    event = PluginActivityEvent.objects.get(action=ActivityAction.GRANT_PURGE_STARTED)
    assert (event.actor_kind, event.detail["reason"], event.detail["previous_state"]) == (
        "platform",
        "grace_period_over",
        "suspended",
    )
    assert any(message.startswith("plugins.retention.tick") and "grants_expired=1" in message for message in log_messages)


def test_without_the_hook_no_job_is_made_and_the_grant_goes_in_the_same_tick(weather_backend, superadmin, acme, clock):
    weather_backend(hooks={"install": False})
    grant = PluginGrantService().grant("weather", acme.pk, superadmin)
    PluginSuspensionService().suspend("weather", grant.pk, superadmin)

    report = _run(clock, days=31)

    assert not PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED).exists()
    assert not PluginGrant.objects.exists()
    assert report.grants_purged == 1


@pytest.mark.parametrize("job_state", [HookJobState.PENDING, HookJobState.RUNNING, HookJobState.FAILED])
def test_the_grant_stays_while_its_plugin_has_not_deleted_its_data(suspended, clock, job_state):
    _run(clock, days=30)
    PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED).update(state=job_state)

    _run(clock, days=30, minutes=1)

    assert PluginGrant.objects.filter(pk=suspended.pk, state=GrantState.PURGING).exists()


@pytest.mark.parametrize("job_state", [HookJobState.SUCCEEDED, HookJobState.SKIPPED])
def test_the_grant_and_everything_hanging_off_it_go_once_both_tracks_are_done(
    suspended, clock, job_state, make_custom_role, acme, log_messages
):
    role = make_custom_role(acme, "Forecasters")
    PluginRolePermission.objects.create(grant=suspended, role=role, permissions=1)
    PluginServiceAccountKey.objects.create(
        service_account=suspended.service_account, prefix="esp_x", key_hash="h" * 64, revoked_at=START
    )
    _run(clock, days=30)
    PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED).update(state=job_state)

    report = _run(clock, days=30, minutes=1)

    assert report.grants_purged == 1
    assert not PluginGrant.objects.exists()
    assert not PluginServiceAccount.objects.exists()
    assert not PluginServiceAccountKey.objects.exists()
    assert not PluginRolePermission.objects.exists()
    job = PluginHookJob.objects.get(kind=HookJobKind.ORG_REMOVED)
    assert job.grant_id is None
    assert PluginActivityEvent.objects.filter(action=ActivityAction.GRANT_PURGED, organization_id=acme.pk).count() == 1
    assert any(message.startswith("plugins.grant.purged") for message in log_messages)


def test_resuming_a_second_before_the_deadline_keeps_everything(suspended, clock, superadmin):
    clock.now = suspended.purge_after - timedelta(seconds=1)
    PluginSuspensionService().resume("weather", suspended.pk, superadmin)

    _run(clock, days=31)

    suspended.refresh_from_db()
    assert suspended.state == GrantState.ACTIVE
    assert PluginOwnedResource.objects.count() == 1


def test_the_data_is_deleted_while_plugins_are_off(suspended, clock, settings):
    settings.PLUGINS_ENABLED = False

    _run(clock, days=30)

    assert PluginGrant.objects.get(pk=suspended.pk).state == GrantState.PURGING
    assert not PluginOwnedResource.objects.exists()


def test_a_grant_the_uninstall_suspended_is_left_to_the_plugin_s_deletion(weather, superadmin, acme, clock, superadmin_client):
    grant = PluginGrantService().grant("weather", acme.pk, superadmin)
    superadmin_client.post("/api/admin/plugins/weather/uninstall/")

    report = _run(clock, days=30)

    assert (report.grants_expired, report.plugins_expired) == (0, 1)
    assert Plugin.objects.get(pk=weather.pk).state == PluginState.PURGING
    event = PluginActivityEvent.objects.get(action=ActivityAction.GRANT_PURGE_STARTED, organization_id=grant.org_id)
    assert (event.actor_kind, event.detail["reason"]) == ("platform", "plugin_deleted")
    assert PluginActivityEvent.objects.get(action=ActivityAction.PLUGIN_PURGE_STARTED).detail == {"reason": "grace_period_over"}


def test_an_uninstalled_plugin_waits_for_its_deadline(weather, clock, superadmin_client):
    superadmin_client.post("/api/admin/plugins/weather/uninstall/")

    _run(clock, days=29)

    assert Plugin.objects.get(pk=weather.pk).state == PluginState.UNINSTALLING


def test_an_overdue_organization_removed_attempt_is_retried(suspended, clock, node_client):
    _run(clock, days=30)
    job = PluginHookJob.objects.get(kind=HookJobKind.ORG_REMOVED)
    assert node_client.post(f"/api/plugin-nodes/self/hook-jobs/{job.pk}/claim/").status_code == 200
    job.refresh_from_db()

    report = _run(clock, days=30, seconds=job.timeout_seconds + 121)

    job.refresh_from_db()
    assert report.hook_attempts_overdue == 1
    assert (job.state, job.next_attempt_at) == (HookJobState.PENDING, clock.now + timedelta(seconds=60))


@pytest.mark.django_db(transaction=True)
def test_two_ticks_at_once_do_the_work_once(weather_backend, superadmin, acme, settings):
    settings.PLUGINS_ENABLED = True
    weather_backend(hooks=HOOKS)
    grant = PluginGrantService().grant("weather", acme.pk, superadmin)
    PluginSuspensionService().suspend("weather", grant.pk, superadmin)
    PluginGrant.objects.filter(pk=grant.pk).update(purge_after=timezone.now() - timedelta(seconds=1))
    start = threading.Barrier(2)

    def tick():
        try:
            start.wait()
            RetentionService().run()
        finally:
            connection.close()

    threads = [threading.Thread(target=tick) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert PluginActivityEvent.objects.filter(action=ActivityAction.GRANT_PURGE_STARTED).count() == 1
    assert PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED).count() == 1


# ---- sessions that slipped past a suspension ----


def test_a_session_that_started_while_a_suspension_committed_is_stopped_within_a_tick(
    weather, superadmin, acme, beta, clock, stopped_sessions, log_messages
):
    grant = PluginGrantService().grant("weather", acme.pk, superadmin)
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    PluginSuspensionService().suspend("weather", grant.pk, superadmin)
    slipped = Session.objects.create(graph=forecast, status=Session.SessionStatus.RUN)
    unrelated = Session.objects.create(graph=flow(beta, "Beta flow"), status=Session.SessionStatus.RUN)

    report = RetentionService().run()

    assert stopped_sessions == [slipped.pk]
    assert unrelated.pk not in stopped_sessions
    assert report.sessions_stopped == 1
    assert any(
        message.startswith("plugins.retention.sessions_stopped") and f"org={acme.pk} count=1" in message
        for message in log_messages
    )


def test_an_organization_with_nothing_to_refuse_is_not_walked(weather, superadmin, acme, stopped_sessions, log_messages):
    grant = PluginGrantService().grant("weather", acme.pk, superadmin)
    own(flow(acme, "Weather forecast"), grant)
    Session.objects.create(graph=flow(acme, "Daily digest"), status=Session.SessionStatus.RUN)

    report = RetentionService().run()

    assert (stopped_sessions, report.sessions_stopped) == ([], 0)
    assert not any(message.startswith("plugins.retention.sessions_stopped") for message in log_messages)


# ---- the hourly housekeeping ----


def test_housekeeping_removes_tombstones_and_keeps_live_and_binned_rows(weather, superadmin, acme, clock):
    grant = PluginGrantService().grant("weather", acme.pk, superadmin)
    live = secret_row(acme, "Live")
    gone = secret_row(acme, "Gone")
    binned = flow(acme, "Binned")
    for row in (live, gone, binned):
        own(row, grant)
    type(gone)._base_manager.filter(pk=gone.pk).delete()
    binned.delete()

    report = HousekeepingService().run()

    assert report.tombstones_removed == 1
    assert set(PluginOwnedResource.objects.values_list("object_id", flat=True)) == {live.pk, binned.pk}


def test_housekeeping_deletes_keys_revoked_more_than_thirty_days_ago(weather, superadmin, acme, clock):
    grant = PluginGrantService().grant("weather", acme.pk, superadmin)
    account = grant.service_account
    old = PluginServiceAccountKey.objects.create(
        service_account=account, prefix="esp_o", key_hash="o" * 64, revoked_at=START - timedelta(days=REVOKED_KEY_RETENTION_DAYS, seconds=1)
    )
    recent = PluginServiceAccountKey.objects.create(
        service_account=account, prefix="esp_r", key_hash="r" * 64, revoked_at=START - timedelta(days=REVOKED_KEY_RETENTION_DAYS - 1)
    )
    current = PluginServiceAccountKey.objects.create(service_account=account, prefix="esp_c", key_hash="c" * 64)

    report = HousekeepingService().run()

    assert report.revoked_keys_removed == 1
    assert set(PluginServiceAccountKey.objects.values_list("pk", flat=True)) == {recent.pk, current.pk}
    assert not PluginServiceAccountKey.objects.filter(pk=old.pk).exists()


def test_housekeeping_fails_install_jobs_without_a_grant_but_keeps_organization_removed_ones(weather, acme, clock):
    install = PluginHookJob.objects.create(
        plugin=weather, organization_id=acme.pk, kind=HookJobKind.INSTALL, timeout_seconds=60
    )
    removal = PluginHookJob.objects.create(
        plugin=weather, organization_id=acme.pk, kind=HookJobKind.ORG_REMOVED, timeout_seconds=60
    )

    report = HousekeepingService().run()

    install.refresh_from_db()
    removal.refresh_from_db()
    assert report.orphaned_hook_jobs_failed == 1
    assert (install.state, install.error) == (HookJobState.FAILED, GRANT_DELETED_BEFORE_HOOK_FINISHED)
    assert removal.state == HookJobState.PENDING


# ---- one failure never ends the tick ----


def test_a_grant_that_fails_leaves_the_others_and_the_plugin_step_to_run(
    weather, superadmin, acme, beta, clock, monkeypatch, log_messages
):
    from plugins.lifecycle.grant_purge_service import GrantPurgeService
    from plugins.lifecycle.plugin_purge_service import PluginPurgeService

    first = PluginGrantService().grant("weather", acme.pk, superadmin)
    second = PluginGrantService().grant("weather", beta.pk, superadmin)
    PluginGrant.objects.filter(pk__in=[first.pk, second.pk]).update(state=GrantState.PURGING, purge_started_at=START)
    tides = Plugin.objects.create(identifier="tides", name="Tides", description="", state=PluginState.PURGING)
    real_finish = GrantPurgeService.finish_if_done

    def finish_or_fail(service, grant):
        if grant.pk == first.pk:
            raise RuntimeError("the database went away")
        return real_finish(service, grant)

    advanced = []
    monkeypatch.setattr(GrantPurgeService, "finish_if_done", finish_or_fail)
    monkeypatch.setattr(PluginPurgeService, "advance", lambda service, plugin, until: advanced.append(plugin.pk) or False)

    report = _run(clock)

    assert PluginGrant.objects.filter(pk=first.pk).exists()
    assert not PluginGrant.objects.filter(pk=second.pk).exists()
    assert advanced == [tides.pk]
    assert report.errors == 1
    assert any(message.startswith(f"Could not move the deletion of grant {first.pk}") for message in log_messages)


def test_a_step_that_fails_leaves_the_next_steps_to_run(suspended, clock, monkeypatch):
    from plugins.lifecycle.hook_job_service import HookJobService

    monkeypatch.setattr(HookJobService, "fail_overdue", lambda service, node=None: 1 / 0)

    report = _run(clock, days=30)

    suspended.refresh_from_db()
    assert suspended.state == GrantState.PURGING
    assert (report.errors, report.grants_expired) == (1, 1)


def test_a_grant_waiting_for_its_data_removal_is_not_checked_every_tick(suspended, clock, monkeypatch):
    from plugins.lifecycle.grant_purge_service import GrantPurgeService

    _run(clock, days=30)
    assert PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED, state=HookJobState.PENDING).exists()
    checked = []
    monkeypatch.setattr(GrantPurgeService, "finish_if_done", lambda service, grant: checked.append(grant.pk) or False)

    _run(clock, days=30, minutes=1)

    assert checked == []


def test_the_sessions_of_every_organization_are_found_in_one_query(weather, superadmin, acme, beta, stopped_sessions):
    from django.test.utils import CaptureQueriesContext
    from plugins.lifecycle.suspended_run_stopper import SuspendedRunStopper
    from rbac.models import Organization

    for organization in (acme, beta):
        grant = PluginGrantService().grant("weather", organization.pk, superadmin)
        own(flow(organization, f"{organization.name} forecast"), grant)
        PluginSuspensionService().suspend("weather", grant.pk, superadmin)
        Session.objects.create(graph=flow(organization, f"{organization.name} digest"), status=Session.SessionStatus.RUN)

    with CaptureQueriesContext(connection) as captured:
        SuspendedRunStopper().stop_in_organizations(Organization.objects.filter(pk__in=[acme.pk, beta.pk]).values_list("pk", flat=True))

    session_queries = [query for query in captured.captured_queries if 'FROM "tables_session"' in query["sql"]]
    assert len(session_queries) == 1


def test_the_housekeeping_runs_by_the_wall_clock(monkeypatch):
    from plugins.lifecycle import retention_scheduler

    jobs = {}

    class Scheduler:
        def __init__(self, **options):
            pass

        def add_job(self, function, **options):
            jobs[options["id"]] = options

        def start(self):
            pass

    class Lock:
        def __init__(self, path):
            pass

        def acquire(self, timeout):
            pass

    monkeypatch.setattr(retention_scheduler, "BackgroundScheduler", Scheduler)
    monkeypatch.setattr(retention_scheduler, "FileLock", Lock)
    monkeypatch.setattr(retention_scheduler, "_owner_lock", None)

    assert retention_scheduler.start_plugin_retention_if_owner()

    assert (jobs["plugin_housekeeping"]["trigger"], jobs["plugin_housekeeping"]["minute"]) == ("cron", 7)
    assert (jobs["plugin_retention"]["trigger"], jobs["plugin_retention"]["seconds"]) == ("interval", 60)


def test_the_frontend_repair_runs_after_the_tick_even_when_the_tick_fails(monkeypatch):
    from plugins.lifecycle import retention_scheduler
    from plugins.lifecycle.retention_service import RetentionService
    from plugins.packages.spa_state_reconciler import SpaStateReconciler

    repaired = []
    monkeypatch.setattr(RetentionService, "run", lambda service: 1 / 0)
    monkeypatch.setattr(SpaStateReconciler, "run", lambda reconciler: repaired.append(True) or 0)

    retention_scheduler.run_retention_tick()

    assert repaired == [True]


# ---- an organization's deletion and a plugin-first lifecycle path ----


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("plugin_lock", ["no_key", "full"])
def test_an_organization_s_deletion_never_deadlocks_with_a_path_that_holds_the_plugin(
    weather_backend, superadmin, acme, settings, plugin_lock
):
    """An uninstall holds the plugin and then wants the organization's grants; the
    organization's deletion holds them and then inserts a job pointing at the plugin, which
    takes `FOR KEY SHARE` on it. Only a full `FOR UPDATE` on the plugin conflicts with that."""
    from django.db import OperationalError, transaction
    from plugins.lifecycle.lifecycle_locks import lock_grants_of, lock_plugin
    from plugins.lifecycle.org_removed_hooks import OrgRemovedHookService

    settings.PLUGINS_ENABLED = True
    weather_backend(hooks=HOOKS)
    grant = PluginGrantService().grant("weather", acme.pk, superadmin)
    both_hold_their_first_lock = threading.Barrier(2, timeout=30)
    errors = []

    def lifecycle_path():
        try:
            with transaction.atomic():
                if plugin_lock == "no_key":
                    plugin = lock_plugin("weather")
                else:
                    plugin = Plugin.objects.select_for_update().get(identifier="weather")
                both_hold_their_first_lock.wait()
                lock_grants_of(plugin)
        except OperationalError as error:
            errors.append(error)
        finally:
            connection.close()

    def organization_deletion():
        try:
            with transaction.atomic():
                held = list(PluginGrant.objects.select_for_update(of=("self",)).filter(pk=grant.pk))
                both_hold_their_first_lock.wait()
                plugin = Plugin.objects.select_related("current_package").get(identifier="weather")
                OrgRemovedHookService().ensure_job(
                    plugin, organization_id=acme.pk, organization_name=acme.name, grant=held[0]
                )
        except OperationalError as error:
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=lifecycle_path), threading.Thread(target=organization_deletion)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    if plugin_lock == "no_key":
        assert errors == []
        assert PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED).count() == 1
    else:
        assert [("deadlock" in str(error)) for error in errors] == [True]
