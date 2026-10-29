"""Upgrade hooks: each organization brought to the new version, with automatic retries."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone
from epicstaff_plugin.hooks import verify_hook_assertion
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.lifecycle.hook_job_service import RESULT_GRACE, HookJobService
from plugins.lifecycle.suspension_service import SUSPENDED_BEFORE_HOOK_FINISHED, PluginSuspensionService
from plugins.lifecycle.upgrade_hooks import UpgradeHookService
from plugins.models import (
    ActivityAction,
    GrantState,
    HookJobKind,
    HookJobState,
    Plugin,
    PluginActivityEvent,
    PluginGrant,
    PluginHookJob,
    PluginState,
)
from src.shared.models.plugin_nodes import HookInvocation

from tests.plugins_tests.conftest import mark_running
from tests.plugins_tests.upgrade_fixtures import active_grant, upgrade_jobs

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

DESIRED_STATE_URL = "/api/plugin-nodes/self/desired-state/"


def _claim(node_client, job):
    return node_client.post(f"/api/plugin-nodes/self/hook-jobs/{job.pk}/claim/")


def _result(node_client, job, attempt, outcome="succeeded", **extra):
    body = {"attempt": attempt, "outcome": outcome, "duration_ms": 900, **extra}
    response = node_client.post(f"/api/plugin-nodes/self/hook-jobs/{job.pk}/result/", body, format="json")
    assert response.status_code == 204, response.content
    return response


@pytest.fixture
def weather(backend_plugin):
    """Weather 0.7.0, running, whose current package declares the upgrade hook."""
    return mark_running(backend_plugin(version="0.7.0", hooks={"upgrade": True}))


@pytest.fixture
def grant(weather, superadmin, acme):
    """Acme, last brought to 0.6.0, upgrading with its pending upgrade job."""
    grant = active_grant(weather, acme, superadmin, version="0.6.0")
    grant.state = GrantState.UPGRADING
    grant.save(update_fields=["state"])
    grant = PluginGrant.objects.select_related("org", "plugin__current_package").get(pk=grant.pk)
    UpgradeHookService().ensure_job(grant)
    return grant


@pytest.fixture
def job(grant):
    return upgrade_jobs(grant).get()


def _fail(node_client, job, error="boom"):
    attempt = HookInvocation.model_validate_json(_claim(node_client, job).content).attempt
    _result(node_client, job, attempt, outcome="failed", error=error)
    job.refresh_from_db()
    return job


def test_ensure_job_returns_the_open_job_instead_of_a_second(grant):
    assert UpgradeHookService().ensure_job(grant).pk == upgrade_jobs(grant).get().pk


def test_a_due_upgrade_job_is_listed_while_the_plugin_runs(job, node_client):
    [listed] = node_client.get(DESIRED_STATE_URL).json()["placements"][0]["hook_jobs"]

    assert (listed["job_id"], listed["kind"]) == (job.pk, "upgrade")


def test_the_call_names_the_running_version_and_the_one_the_organization_comes_from(job, node_client, grant):
    response = _claim(node_client, job)

    assert response.status_code == 200
    invocation = HookInvocation.model_validate_json(response.content)
    verified = verify_hook_assertion(
        invocation.assertion,
        invocation.body.encode("utf-8"),
        kind="upgrade",
        jwks=PluginSigningKeyService().jwks(),
        issuer="http://epicstaff.localhost",
        plugin_identifier="weather",
    )
    body = json.loads(invocation.body)
    assert (body["kind"], body["plugin"]["version"], body["previous_version"]) == ("upgrade", "0.7.0", "0.6.0")
    assert verified.request.previous_version == "0.6.0"
    assert invocation.timeout_seconds == 1800
    job.refresh_from_db()
    assert (job.previous_version, job.package_id) == ("0.6.0", grant.plugin.current_package_id)


@pytest.mark.parametrize(
    "change",
    ["plugin_not_running", "grant_not_upgrading", "not_due"],
)
def test_a_claim_needs_a_running_plugin_an_upgrading_grant_and_a_due_job(job, grant, weather, node_client, change):
    if change == "plugin_not_running":
        Plugin.objects.filter(pk=weather.pk).update(state=PluginState.MAINTENANCE)
    elif change == "grant_not_upgrading":
        PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.ACTIVE)
    else:
        PluginHookJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now() + timedelta(minutes=1))

    response = _claim(node_client, job)

    assert (response.status_code, response.json()["code"]) == (409, "hook_job_not_claimable")


def test_success_brings_the_organization_to_the_version(job, grant, node_client):
    attempt = HookInvocation.model_validate_json(_claim(node_client, job).content).attempt

    _result(node_client, job, attempt)

    grant.refresh_from_db()
    assert (grant.state, grant.installed_version, grant.last_hook_error) == (GrantState.ACTIVE, "0.7.0", None)
    event = PluginActivityEvent.objects.get(action=ActivityAction.UPGRADE_HOOK_SUCCEEDED)
    assert event.organization_id == grant.org_id
    assert event.detail == {"job_id": job.pk, "attempt": 1, "from_version": "0.6.0", "to_version": "0.7.0"}


def test_failures_are_retried_after_one_then_five_minutes_then_wait_for_a_retry(job, grant, node_client, superadmin):
    started = timezone.now()

    first = _fail(node_client, job, "first")
    assert (first.state, first.failures_in_series, first.error) == (HookJobState.PENDING, 1, "first")
    assert timedelta(seconds=55) < first.next_attempt_at - started < timedelta(seconds=70)
    grant.refresh_from_db()
    assert (grant.state, grant.last_hook_error) == (GrantState.UPGRADING, "first")

    PluginHookJob.objects.filter(pk=job.pk).update(next_attempt_at=None)
    second = _fail(node_client, job, "second")
    assert (second.state, second.failures_in_series) == (HookJobState.PENDING, 2)
    assert timedelta(seconds=290) < second.next_attempt_at - timezone.now() <= timedelta(seconds=300)

    PluginHookJob.objects.filter(pk=job.pk).update(next_attempt_at=None)
    third = _fail(node_client, job, "third")
    assert (third.state, third.next_attempt_at, third.finished_at is not None) == (HookJobState.FAILED, None, True)
    grant.refresh_from_db()
    assert (grant.state, grant.last_hook_error) == (GrantState.UPGRADE_FAILED, "third")
    assert Plugin.objects.with_summary().get(pk=grant.plugin_id).needs_attention
    failures = PluginActivityEvent.objects.filter(action=ActivityAction.UPGRADE_HOOK_FAILED).order_by("pk")
    assert [event.detail["next_attempt_at"] is None for event in failures] == [False, False, True]


def test_a_retry_puts_the_failed_job_back_with_a_fresh_series(job, grant, node_client, superadmin_client):
    PluginHookJob.objects.filter(pk=job.pk).update(state=HookJobState.FAILED, failures_in_series=3, error="x")
    PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.UPGRADE_FAILED)

    response = superadmin_client.post(f"/api/admin/plugins/weather/grants/{grant.pk}/retry-hook/")

    assert response.status_code == 202, response.content
    assert response.json()["state"] == "upgrading"
    job.refresh_from_db()
    assert (job.state, job.failures_in_series, job.next_attempt_at, job.error) == (HookJobState.PENDING, 0, None, None)
    assert PluginActivityEvent.objects.get(action=ActivityAction.UPGRADE_HOOK_RETRIED).detail == {"job_id": job.pk}


def test_a_retry_of_a_grant_whose_upgrade_did_not_fail_is_refused(grant, superadmin_client):
    response = superadmin_client.post(f"/api/admin/plugins/weather/grants/{grant.pk}/retry-hook/")

    assert (response.status_code, response.json()["code"]) == (409, "hook_not_retryable")


def test_a_success_during_maintenance_leaves_the_organization_upgrading(job, grant, weather, node_client):
    attempt = HookInvocation.model_validate_json(_claim(node_client, job).content).attempt
    Plugin.objects.filter(pk=weather.pk).update(state=PluginState.MAINTENANCE)

    _result(node_client, job, attempt)

    grant.refresh_from_db()
    assert (grant.state, grant.installed_version) == (GrantState.UPGRADING, "0.7.0")


def test_a_result_that_never_comes_counts_as_a_failure(job, grant, node_client):
    _claim(node_client, job)
    PluginHookJob.objects.filter(pk=job.pk).update(deadline_at=timezone.now() - RESULT_GRACE - timedelta(seconds=1))

    assert HookJobService().fail_overdue() == 1

    job.refresh_from_db()
    assert (job.state, job.failures_in_series) == (HookJobState.PENDING, 1)


def test_suspending_an_upgrading_grant_fails_its_job_and_says_why(job, grant, superadmin):
    PluginSuspensionService().suspend("weather", grant.pk, superadmin)

    job.refresh_from_db()
    grant.refresh_from_db()
    assert (job.state, job.error) == (HookJobState.FAILED, SUSPENDED_BEFORE_HOOK_FINISHED)
    assert grant.last_hook_error == SUSPENDED_BEFORE_HOOK_FINISHED


def test_suspending_a_grant_whose_upgrade_failed_is_allowed(job, grant, superadmin):
    PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.UPGRADE_FAILED)

    PluginSuspensionService().suspend("weather", grant.pk, superadmin)

    grant.refresh_from_db()
    assert grant.state == GrantState.SUSPENDED


def test_resuming_after_a_version_change_upgrades_the_organization(grant, job, superadmin):
    PluginSuspensionService().suspend("weather", grant.pk, superadmin)

    PluginSuspensionService().resume("weather", grant.pk, superadmin)

    grant.refresh_from_db()
    assert grant.state == GrantState.UPGRADING
    assert upgrade_jobs(grant).filter(state=HookJobState.PENDING).count() == 1


def test_resuming_while_the_plugin_is_in_maintenance_waits_without_a_job(grant, job, weather, superadmin):
    PluginSuspensionService().suspend("weather", grant.pk, superadmin)
    Plugin.objects.filter(pk=weather.pk).update(state=PluginState.MAINTENANCE)

    PluginSuspensionService().resume("weather", grant.pk, superadmin)

    grant.refresh_from_db()
    assert grant.state == GrantState.UPGRADING
    assert not upgrade_jobs(grant).filter(state=HookJobState.PENDING).exists()


def test_resuming_on_the_installed_version_is_active(weather, superadmin, acme):
    grant = active_grant(weather, acme, superadmin)
    PluginSuspensionService().suspend("weather", grant.pk, superadmin)

    PluginSuspensionService().resume("weather", grant.pk, superadmin)

    grant.refresh_from_db()
    assert grant.state == GrantState.ACTIVE
    assert not upgrade_jobs(grant).exists()


def test_an_upgrading_organization_s_key_still_authenticates(grant, weather, service_account_key):
    from plugins.identity.service_account_keys import ServiceAccountKeyService

    minted = ServiceAccountKeyService().mint_for_plugin(weather)

    assert [key.service_account.grant_id for key in minted] == [grant.pk]
    assert HookJobKind.UPGRADE in dict(HookJobKind.choices)
