"""Install hooks: the grant that waits for one, the node's claim and result, retries, overdue jobs."""

import json
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from epicstaff_plugin.contracts.hook_api import HookRequest
from epicstaff_plugin.contracts.manifest import MAX_HOOK_TIMEOUT_SECONDS
from epicstaff_plugin.hooks import verify_hook_assertion
from plugins.identity.service_account_keys import ServiceAccountKeyService
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.lifecycle.hook_job_service import HookJobService
from plugins.lifecycle.suspension_service import PluginSuspensionService
from plugins.models import (
    GrantState,
    HookJobState,
    PluginActivityEvent,
    PluginGrant,
    PluginHookJob,
    PluginServiceAccount,
)
from rbac.models import Organization
from src.shared.models.plugin_nodes import MAX_PENDING_HOOK_JOBS, HookInvocation, HookResult

from tests.plugins_tests.conftest import mark_running

pytestmark = [pytest.mark.django_db]

DESIRED_STATE_URL = "/api/plugin-nodes/self/desired-state/"
REPORTS_URL = "/api/plugin-nodes/self/reports/"
INSTALL_HOOK = {"install": True}


def _claim_url(job_id):
    return f"/api/plugin-nodes/self/hook-jobs/{job_id}/claim/"


def _result_url(job_id):
    return f"/api/plugin-nodes/self/hook-jobs/{job_id}/result/"


def _grant(superadmin_client, organization):
    response = superadmin_client.post("/api/admin/plugins/weather/grants/", {"organization_id": organization.pk}, format="json")
    assert response.status_code == 201, response.content
    return response.json()


def _result(node_client, job_id, attempt, outcome="succeeded", **extra):
    body = {"attempt": attempt, "outcome": outcome, "duration_ms": 1200, **extra}
    return node_client.post(_result_url(job_id), body, format="json")


def _desired_jobs(node_client):
    return node_client.get(DESIRED_STATE_URL).json()["placements"][0]["hook_jobs"]


@pytest.fixture
def hooked_weather(weather_backend):
    return weather_backend(hooks=INSTALL_HOOK)


@pytest.fixture
def job(hooked_weather, superadmin_client, acme):
    _grant(superadmin_client, acme)
    return PluginHookJob.objects.get()


# ---- the grant state machine ----


def test_a_plugin_without_a_backend_is_granted_active_without_a_service_account(
    running_plugin, superadmin_client, acme, service_account_platform
):
    running_plugin()

    grant = _grant(superadmin_client, acme)

    assert grant["state"] == "active"
    assert grant["service_account"] is None
    assert grant["install_hook"] is None
    assert not PluginServiceAccount.objects.exists()


def test_a_backend_without_an_install_hook_is_granted_active_with_a_service_account(
    weather_backend, superadmin_client, acme, plugin_node
):
    weather_backend()

    grant = _grant(superadmin_client, acme)

    assert grant["state"] == "active"
    assert grant["service_account"]["key_last_used_at"] is None
    assert grant["install_hook"] is None
    assert PluginServiceAccount.objects.get().grant_id == grant["id"]
    assert not PluginHookJob.objects.exists()


def test_a_backend_with_an_install_hook_is_granting_with_a_pending_job(hooked_weather, superadmin_client, acme):
    grant = _grant(superadmin_client, acme)

    assert grant["state"] == "granting"
    assert grant["service_account"] is not None
    assert grant["install_hook"] == {"state": "pending", "attempt": 0, "started_at": None, "finished_at": None, "error": None}
    job = PluginHookJob.objects.get()
    assert (job.kind, job.organization_id, job.grant_id) == ("install", acme.pk, grant["id"])


def test_the_job_s_timeout_comes_from_the_manifest(weather_backend, superadmin_client, acme):
    weather_backend(hooks={"install": True, "timeouts_seconds": {"install": 45}})

    _grant(superadmin_client, acme)

    assert PluginHookJob.objects.get().timeout_seconds == 45


def test_without_a_manifest_timeout_the_platform_maximum_applies(job):
    assert job.timeout_seconds == MAX_HOOK_TIMEOUT_SECONDS["install"]


# ---- desired state and claim ----


def test_the_desired_state_lists_the_pending_job_and_drops_it_once_claimed(job, node_client, acme):
    assert _desired_jobs(node_client) == [{"job_id": job.pk, "kind": "install", "organization_id": acme.pk}]

    assert node_client.post(_claim_url(job.pk)).status_code == 200

    assert _desired_jobs(node_client) == []


def test_a_job_whose_grant_is_gone_is_not_listed(job, node_client):
    PluginGrant.objects.all().delete()

    assert _desired_jobs(node_client) == []


def test_a_claim_hands_over_a_signed_call_bound_to_its_body(job, node_client, acme, hooked_weather):
    response = node_client.post(_claim_url(job.pk))

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    invocation = HookInvocation.model_validate_json(response.content)
    assert (invocation.job_id, invocation.kind, invocation.attempt, invocation.organization_id) == (job.pk, "install", 1, acme.pk)
    assert invocation.timeout_seconds == job.timeout_seconds
    verified = verify_hook_assertion(
        invocation.assertion,
        invocation.body.encode("utf-8"),
        kind="install",
        jwks=PluginSigningKeyService().jwks(),
        issuer="http://epicstaff.localhost",
        plugin_identifier="weather",
    )
    assert (verified.claims.job_id, verified.claims.attempt, verified.claims.org_id) == (job.pk, 1, acme.pk)
    assert verified.request == HookRequest.model_validate(json.loads(invocation.body))
    assert verified.request.org.name == acme.name
    assert verified.request.plugin.version == hooked_weather.current_package.version
    assert verified.claims.exp - verified.claims.iat == job.timeout_seconds + 60
    job.refresh_from_db()
    assert job.state == HookJobState.RUNNING
    assert job.deadline_at - job.claimed_at == timedelta(seconds=job.timeout_seconds)


def test_the_assertion_does_not_verify_with_another_body(job, node_client):
    from epicstaff_plugin.hooks import HookAssertionRejected

    invocation = HookInvocation.model_validate_json(node_client.post(_claim_url(job.pk)).content)
    other_body = invocation.body.replace('"attempt":1', '"attempt":2').encode()

    with pytest.raises(HookAssertionRejected):
        verify_hook_assertion(
            invocation.assertion,
            other_body,
            kind="install",
            jwks=PluginSigningKeyService().jwks(),
            issuer="http://epicstaff.localhost",
            plugin_identifier="weather",
        )


def test_a_second_claim_is_refused(job, node_client):
    node_client.post(_claim_url(job.pk))

    response = node_client.post(_claim_url(job.pk))

    assert response.status_code == 409
    assert response.json()["code"] == "hook_job_not_claimable"


def test_a_job_of_a_plugin_that_is_not_running_cannot_be_claimed(job, node_client, hooked_weather):
    type(hooked_weather).objects.filter(pk=hooked_weather.pk).update(state="failed")

    assert node_client.post(_claim_url(job.pk)).status_code == 409


def test_another_node_s_job_is_not_found(job, other_node_client):
    for response in (other_node_client.post(_claim_url(job.pk)), _result(other_node_client, job.pk, 1)):
        assert response.status_code == 404
        assert response.json()["code"] == "hook_job_not_found"


def test_an_unknown_job_is_not_found(plugin_node, node_client, service_account_platform):
    assert node_client.post(_claim_url(999999)).status_code == 404


# ---- results ----


def test_a_successful_result_activates_the_grant(job, node_client, acme):
    node_client.post(_claim_url(job.pk))

    response = _result(node_client, job.pk, 1, http_status=200)

    assert response.status_code == 204
    grant = PluginGrant.objects.get()
    assert (grant.state, grant.last_hook_error) == (GrantState.ACTIVE, None)
    job.refresh_from_db()
    assert (job.state, job.error) == (HookJobState.SUCCEEDED, None)
    event = PluginActivityEvent.objects.get(action="install_hook_succeeded")
    assert (event.actor_kind, event.actor_label, event.organization_id) == ("platform", "Platform", acme.pk)
    assert event.detail == {"job_id": job.pk, "attempt": 1}


def test_a_failed_result_fails_the_grant_with_the_error(job, node_client, superadmin_client):
    node_client.post(_claim_url(job.pk))

    _result(node_client, job.pk, 1, outcome="failed", error="Open-Meteo did not answer", http_status=500)

    grant = PluginGrant.objects.get()
    assert (grant.state, grant.last_hook_error) == (GrantState.INSTALL_FAILED, "Open-Meteo did not answer")
    event = PluginActivityEvent.objects.get(action="install_hook_failed")
    assert event.detail == {"job_id": job.pk, "attempt": 1, "error": "Open-Meteo did not answer"}
    listed = superadmin_client.get("/api/admin/plugins/weather/grants/").json()["results"][0]
    assert listed["state"] == "install_failed"
    assert listed["install_hook"]["state"] == "failed"
    assert listed["install_hook"]["error"] == "Open-Meteo did not answer"
    assert listed["install_hook"]["started_at"] and listed["install_hook"]["finished_at"]


def test_a_result_for_another_attempt_is_refused(job, node_client):
    node_client.post(_claim_url(job.pk))

    response = _result(node_client, job.pk, 2)

    assert response.status_code == 409
    assert response.json()["code"] == "hook_job_not_running"
    assert PluginGrant.objects.get().state == GrantState.GRANTING


def test_a_result_for_a_job_that_is_not_running_is_refused(job, node_client):
    assert _result(node_client, job.pk, 1).status_code == 409


@pytest.mark.parametrize(
    "body",
    [{}, {"attempt": 1, "outcome": "maybe", "duration_ms": 1}, {"attempt": 0, "outcome": "succeeded", "duration_ms": 1}, {"attempt": 1, "outcome": "failed", "duration_ms": 1, "error": "x" * 2001}],
    ids=["empty", "unknown-outcome", "attempt-zero", "error-too-long"],
)
def test_a_malformed_result_is_invalid(job, node_client, body):
    node_client.post(_claim_url(job.pk))

    response = node_client.post(_result_url(job.pk), body, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_hook_result"
    assert all(error["loc"].startswith("result") for error in response.json()["errors"])


# ---- retry ----


def _retry(superadmin_client, grant_id, identifier="weather"):
    return superadmin_client.post(f"/api/admin/plugins/{identifier}/grants/{grant_id}/retry-hook/")


def test_a_retry_puts_the_same_job_back_and_the_next_claim_is_the_next_attempt(job, node_client, superadmin_client, superadmin_user):
    node_client.post(_claim_url(job.pk))
    _result(node_client, job.pk, 1, outcome="failed", error="boom")

    response = _retry(superadmin_client, job.grant_id)

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "granting"
    assert body["allowed_actions"] == ["suspend", "purge"]
    assert body["install_hook"]["state"] == "pending"
    assert body["install_hook"]["error"] is None
    assert PluginHookJob.objects.get().pk == job.pk
    event = PluginActivityEvent.objects.get(action="install_hook_retried")
    assert (event.actor_kind, event.actor_user_id, event.detail) == ("superadmin", superadmin_user.pk, {"job_id": job.pk})

    invocation = HookInvocation.model_validate_json(node_client.post(_claim_url(job.pk)).content)
    assert invocation.attempt == 2
    _result(node_client, job.pk, 2)
    assert PluginGrant.objects.get().state == GrantState.ACTIVE


def test_retrying_a_grant_whose_hook_has_not_failed_conflicts(job, superadmin_client):
    response = _retry(superadmin_client, job.grant_id)

    assert response.status_code == 409
    assert response.json()["code"] == "hook_not_retryable"


def test_retrying_an_unknown_grant_or_one_of_another_plugin_is_not_found(job, superadmin_client, running_plugin, grant_to, beta):
    other = running_plugin(id="forecast", name="Forecast")
    other_grant = grant_to(other, beta)

    for grant_id, identifier in ((999999, "weather"), (other_grant.pk, "weather"), (job.grant_id, "forecast")):
        response = _retry(superadmin_client, grant_id, identifier)
        assert response.status_code == 404
        assert response.json()["code"] == "grant_not_found"


def test_only_a_superadmin_may_retry(job, client_as, admin_acme):
    assert _retry(client_as(admin_acme), job.grant_id).status_code == 403


# ---- overdue jobs ----


def _report(node_client, plugin):
    entry = {
        "placement_id": plugin.placement.pk,
        "observed_state": "running",
        "observed_version": plugin.current_package.version,
        "health": "ok",
        "restarts": 0,
        "applied_settings_revision": 0,
        "applied_restart_generation": 0,
    }
    body = {"format": 1, "agent_version": "0.1.0", "reported_at": "2026-10-21T08:00:05Z", "placements": [entry]}
    return node_client.post(REPORTS_URL, body, format="json")


def test_a_running_job_without_a_result_fails_at_the_next_report_after_its_deadline(job, node_client, hooked_weather):
    node_client.post(_claim_url(job.pk))
    PluginHookJob.objects.update(deadline_at=timezone.now() - timedelta(seconds=121))

    assert _report(node_client, mark_running(hooked_weather)).status_code == 204

    job.refresh_from_db()
    assert (job.state, job.error) == (HookJobState.FAILED, "The plugin node reported no result in time")
    grant = PluginGrant.objects.get()
    assert (grant.state, grant.last_hook_error) == (GrantState.INSTALL_FAILED, "The plugin node reported no result in time")
    assert PluginActivityEvent.objects.filter(action="install_hook_failed").count() == 1


def test_a_running_job_within_its_grace_period_keeps_running(job, node_client, hooked_weather):
    node_client.post(_claim_url(job.pk))
    PluginHookJob.objects.update(deadline_at=timezone.now() - timedelta(seconds=60))

    _report(node_client, mark_running(hooked_weather))

    job.refresh_from_db()
    assert job.state == HookJobState.RUNNING


def test_an_overdue_job_is_failed_before_a_claim_too(job, node_client, superadmin_client):
    node_client.post(_claim_url(job.pk))
    PluginHookJob.objects.update(deadline_at=timezone.now() - timedelta(seconds=121))

    assert node_client.post(_claim_url(job.pk)).status_code == 409

    assert PluginGrant.objects.get().state == GrantState.INSTALL_FAILED


# ---- suspension ----


def _suspend(superadmin_client, grant_id):
    response = superadmin_client.post(f"/api/admin/plugins/weather/grants/{grant_id}/suspend/")
    assert response.status_code == 200, response.content


def test_a_result_for_a_job_the_suspension_failed_conflicts_and_the_grant_stays_suspended(job, node_client, superadmin_client):
    node_client.post(_claim_url(job.pk))
    _suspend(superadmin_client, job.grant_id)

    response = _result(node_client, job.pk, 1)

    assert (response.status_code, response.json()["code"]) == (409, "hook_job_not_running")
    assert PluginGrant.objects.get().state == GrantState.SUSPENDED


def test_a_job_of_a_suspended_grant_cannot_be_claimed(job, node_client, superadmin_client):
    _suspend(superadmin_client, job.grant_id)
    # Put the job back as if the suspension had missed it: the grant's state alone refuses it.
    PluginHookJob.objects.filter(pk=job.pk).update(state=HookJobState.PENDING)

    response = node_client.post(_claim_url(job.pk))

    assert (response.status_code, response.json()["code"]) == (409, "hook_job_not_claimable")


# ---- lock order: the grant first, then its jobs, then its service account, everywhere ----


def _locked_tables(captured):
    """The tables each `SELECT ... FOR UPDATE` (or `FOR NO KEY UPDATE`) locked, in order."""
    tables = []
    for query in captured.captured_queries:
        sql = query["sql"]
        if "FOR UPDATE" not in sql and "FOR NO KEY UPDATE" not in sql:
            continue
        from_clause = sql.split(" FROM ", 1)[1]
        if from_clause.startswith('"plugins_plugin" '):
            tables.append("plugin")
        elif from_clause.startswith('"plugins_plugingrant"'):
            tables.append("grant")
        elif from_clause.startswith('"plugins_pluginhookjob"'):
            tables.append("job")
        elif from_clause.startswith('"plugins_pluginserviceaccount"'):
            tables.append("account")
        else:
            tables.append(from_clause.split(" ", 1)[0])
    return tables


def _locks_of(call):
    with CaptureQueriesContext(connection) as captured:
        call()
    return _locked_tables(captured)


def test_a_claim_locks_the_grant_before_the_job(job, plugin_node):
    assert _locks_of(lambda: HookJobService().claim(plugin_node, job.pk)) == ["grant", "job"]


def test_a_result_locks_the_grant_before_the_job(job, plugin_node):
    HookJobService().claim(plugin_node, job.pk)

    locks = _locks_of(
        lambda: HookJobService().record_result(
            plugin_node, job.pk, HookResult(attempt=1, outcome="succeeded", duration_ms=5)
        )
    )

    assert locks == ["grant", "job"]


def test_failing_an_overdue_job_locks_the_grant_before_the_job(job, plugin_node):
    HookJobService().claim(plugin_node, job.pk)
    PluginHookJob.objects.update(deadline_at=timezone.now() - timedelta(seconds=121))

    assert _locks_of(lambda: HookJobService().fail_overdue(plugin_node)) == ["grant", "job"]


def test_a_retry_locks_the_plugin_then_the_grant_then_the_job(job, plugin_node, superadmin):
    HookJobService().claim(plugin_node, job.pk)
    HookJobService().record_result(plugin_node, job.pk, HookResult(attempt=1, outcome="failed", duration_ms=5))

    assert _locks_of(lambda: HookJobService().retry("weather", job.grant_id, superadmin)) == ["plugin", "grant", "job"]


def test_a_suspension_locks_the_plugin_the_grant_its_jobs_then_its_service_account(job, superadmin):
    locks = _locks_of(lambda: PluginSuspensionService().suspend("weather", job.grant_id, superadmin))

    assert locks == ["plugin", "grant", "job", "account"]


def test_a_resume_locks_the_plugin_and_the_grant_before_its_service_account(job, superadmin):
    PluginSuspensionService().suspend("weather", job.grant_id, superadmin)

    assert _locks_of(lambda: PluginSuspensionService().resume("weather", job.grant_id, superadmin)) == [
        "plugin",
        "grant",
        "account",
    ]


def test_minting_keys_locks_the_service_accounts_before_their_keys(job, hooked_weather):
    # The keys are changed by UPDATEs once the accounts are locked, as `_revoke_keys` does
    # after it locks the account: both take the account first, so neither waits on the other.
    assert _locks_of(lambda: ServiceAccountKeyService().mint_for_plugin(hooked_weather)) == ["account"]


# ---- many pending jobs ----


def test_a_plugin_with_more_pending_jobs_than_a_placement_carries_lists_the_oldest(hooked_weather, node_client, superadmin):
    organizations = Organization.objects.bulk_create(
        [Organization(name=f"Pending {number:04}") for number in range(MAX_PENDING_HOOK_JOBS + 1)]
    )
    grants = PluginGrant.objects.bulk_create(
        [
            PluginGrant(plugin=hooked_weather, org=organization, state=GrantState.GRANTING, created_by=superadmin)
            for organization in organizations
        ]
    )
    jobs = PluginHookJob.objects.bulk_create(
        [
            PluginHookJob(
                plugin=hooked_weather,
                grant=grant,
                organization_id=grant.org_id,
                kind="install",
                package=hooked_weather.current_package,
                timeout_seconds=60,
            )
            for grant in grants
        ]
    )

    response = node_client.get(DESIRED_STATE_URL)

    assert response.status_code == 200, response.content
    listed = [entry["job_id"] for entry in response.json()["placements"][0]["hook_jobs"]]
    assert listed == sorted(job.pk for job in jobs)[:MAX_PENDING_HOOK_JOBS]
