"""Organization removed hooks: creating the job, the node running it, retries, retry and skip."""

import json
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from epicstaff_plugin.contracts.hook_api import (
    ORG_REMOVED_RETRY_WINDOW_SECONDS,
    HookRequest,
)
from epicstaff_plugin.hooks import verify_hook_assertion
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.lifecycle.hook_job_service import HookJobService
from plugins.lifecycle.org_removed_hooks import OrgRemovedHookService, allowed_org_removed_job_actions
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


pytestmark = [pytest.mark.django_db]

START = datetime(2026, 10, 21, 12, 0, tzinfo=dt_timezone.utc)
DESIRED_STATE_URL = "/api/plugin-nodes/self/desired-state/"
HOOKS = {"install": False, "org_removed": True}


class Clock:
    def __init__(self):
        self.now = START

    def advance(self, **delta):
        self.now += timedelta(**delta)
        return self.now


@pytest.fixture
def clock(monkeypatch):
    frozen = Clock()
    monkeypatch.setattr(timezone, "now", lambda: frozen.now)
    return frozen


@pytest.fixture
def weather(weather_backend):
    return weather_backend(hooks=HOOKS)


@pytest.fixture
def purging_grant(weather, grant_to, acme):
    return grant_to(weather, acme, state=GrantState.PURGING)


@pytest.fixture
def job(weather, purging_grant, acme):
    return _ensure(weather, acme, purging_grant)


def _ensure(plugin, organization, grant=None):
    plugin = Plugin.objects.select_related("current_package").get(pk=plugin.pk)
    return OrgRemovedHookService().ensure_job(
        plugin, organization_id=organization.pk, organization_name=organization.name, grant=grant
    )


def _claim(node_client, job):
    return node_client.post(f"/api/plugin-nodes/self/hook-jobs/{job.pk}/claim/")


def _result(node_client, job, outcome="failed", error="The database is busy"):
    job.refresh_from_db()
    body = {"attempt": job.attempt, "outcome": outcome, "duration_ms": 10}
    if outcome == "failed":
        body["error"] = error
    response = node_client.post(f"/api/plugin-nodes/self/hook-jobs/{job.pk}/result/", body, format="json")
    assert response.status_code == 204, response.content
    job.refresh_from_db()
    return job


def _attempt(node_client, job, clock, outcome="failed"):
    """Claim the job once it is due, and post `outcome`."""
    job.refresh_from_db()
    if job.next_attempt_at is not None and job.next_attempt_at > clock.now:
        clock.now = job.next_attempt_at
    response = _claim(node_client, job)
    assert response.status_code == 200, response.content
    return _result(node_client, job, outcome)


def _listed(node_client):
    placements = node_client.get(DESIRED_STATE_URL).json()["placements"]
    return [job["job_id"] for placement in placements for job in placement["hook_jobs"]]


# ---- creating the job ----


def test_a_job_keeps_the_organization_s_id_and_name(job, acme, purging_grant, weather):
    assert (job.kind, job.state, job.organization_id, job.organization_name) == (
        HookJobKind.ORG_REMOVED,
        HookJobState.PENDING,
        acme.pk,
        acme.name,
    )
    assert (job.grant_id, job.package_id) == (purging_grant.pk, weather.current_package_id)
    assert job.timeout_seconds == 900


def test_no_job_without_the_hook_or_without_a_backend(weather_backend, running_plugin, acme):
    without_hook = weather_backend(hooks={"install": False})
    assert _ensure(without_hook, acme) is None
    Plugin.objects.filter(pk=without_hook.pk).delete()
    assert _ensure(running_plugin(), acme) is None


@pytest.mark.parametrize("state", [HookJobState.PENDING, HookJobState.RUNNING, HookJobState.FAILED])
def test_an_unfinished_job_is_returned_instead_of_a_second(job, weather, acme, state):
    PluginHookJob.objects.filter(pk=job.pk).update(state=state)

    assert _ensure(weather, acme).pk == job.pk
    assert PluginHookJob.objects.count() == 1


@pytest.mark.parametrize("state", [HookJobState.SUCCEEDED, HookJobState.SKIPPED])
def test_a_finished_job_gives_way_to_a_new_one(job, weather, acme, state):
    PluginHookJob.objects.filter(pk=job.pk).update(state=state)

    assert _ensure(weather, acme).pk != job.pk


def test_the_database_refuses_a_second_open_job_for_the_organization(job, weather, acme):
    with pytest.raises(IntegrityError), transaction.atomic():
        PluginHookJob.objects.create(
            plugin=weather,
            organization_id=acme.pk,
            kind=HookJobKind.ORG_REMOVED,
            timeout_seconds=60,
        )


def test_a_creation_that_loses_a_race_returns_the_winner_s_job(job, weather, acme, monkeypatch):
    found = iter([None, job])
    monkeypatch.setattr(OrgRemovedHookService, "_unfinished_job", staticmethod(lambda plugin, organization_id: next(found)))

    with transaction.atomic():
        assert _ensure(weather, acme).pk == job.pk
        # The caller's transaction is still usable.
        assert PluginHookJob.objects.count() == 1


# ---- the node runs it ----


def test_the_claim_signs_a_body_with_the_organization_as_it_was(job, node_client, acme, weather):
    acme.name = "Acme renamed"
    acme.save(update_fields=["name"])

    response = _claim(node_client, job)

    assert response.status_code == 200, response.content
    invocation = HookInvocation.model_validate_json(response.content)
    verified = verify_hook_assertion(
        invocation.assertion,
        invocation.body.encode("utf-8"),
        kind="org_removed",
        jwks=PluginSigningKeyService().jwks(),
        issuer="http://epicstaff.localhost",
        plugin_identifier="weather",
    )
    assert verified.request == HookRequest.model_validate(json.loads(invocation.body))
    assert (verified.request.org.id, verified.request.org.name) == (acme.pk, job.organization_name)
    assert job.organization_name != "Acme renamed"
    assert verified.request.plugin.version == weather.current_package.version
    job.refresh_from_db()
    assert job.first_attempt_at is not None


def test_a_job_whose_organization_is_gone_is_claimable(job, node_client, acme):
    PluginHookJob.objects.filter(pk=job.pk).update(grant=None)
    acme.delete()

    assert _claim(node_client, job).status_code == 200


@pytest.mark.parametrize("grant_state", [GrantState.ACTIVE, GrantState.SUSPENDED, GrantState.GRANTING])
def test_a_job_whose_grant_is_not_being_purged_is_not_claimable(job, node_client, purging_grant, grant_state):
    PluginGrant.objects.filter(pk=purging_grant.pk).update(state=grant_state)

    response = _claim(node_client, job)

    assert response.status_code == 409
    assert response.json()["code"] == "hook_job_not_claimable"


@pytest.mark.parametrize("plugin_state", [PluginState.UNINSTALLING, PluginState.PURGING])
def test_an_uninstalled_or_deleting_plugin_runs_its_job(job, node_client, weather, plugin_state):
    Plugin.objects.filter(pk=weather.pk).update(state=plugin_state)

    assert _claim(node_client, job).status_code == 200


@pytest.mark.parametrize("plugin_state", [PluginState.PROVISIONING, PluginState.FAILED])
def test_a_plugin_that_is_not_up_does_not_run_its_job(job, node_client, weather, plugin_state):
    Plugin.objects.filter(pk=weather.pk).update(state=plugin_state)

    assert _claim(node_client, job).status_code == 409


def test_a_job_waiting_for_its_next_attempt_is_neither_listed_nor_claimable(job, node_client, clock):
    PluginHookJob.objects.filter(pk=job.pk).update(next_attempt_at=clock.now + timedelta(minutes=5))

    assert _listed(node_client) == []
    assert _claim(node_client, job).status_code == 409

    clock.advance(minutes=5)

    assert _listed(node_client) == [job.pk]


@pytest.mark.parametrize(
    ("plugin_state", "listed"),
    [
        (PluginState.RUNNING, True),
        (PluginState.UNINSTALLING, True),
        (PluginState.PURGING, True),
        (PluginState.FAILED, False),
        (PluginState.PROVISIONING, False),
    ],
)
def test_the_desired_state_lists_a_due_job_only_while_the_plugin_can_run_it(job, node_client, weather, plugin_state, listed):
    Plugin.objects.filter(pk=weather.pk).update(state=plugin_state)

    assert _listed(node_client) == ([job.pk] if listed else [])


def test_success_finishes_the_job_records_it_and_never_moves_the_grant(job, node_client, clock, purging_grant):
    _attempt(node_client, job, clock, outcome="succeeded")

    job.refresh_from_db()
    assert (job.state, job.finished_at) == (HookJobState.SUCCEEDED, clock.now)
    purging_grant.refresh_from_db()
    assert purging_grant.state == GrantState.PURGING
    event = PluginActivityEvent.objects.get(action=ActivityAction.ORG_REMOVED_HOOK_SUCCEEDED)
    assert (event.organization_id, event.actor_kind, event.detail) == (job.organization_id, "platform", {"job_id": job.pk, "attempt": 1})


# ---- retries ----


def test_failures_are_retried_on_the_schedule_from_the_first_attempt(job, node_client, clock, purging_grant):
    delays = []
    for _ in range(6):
        job = _attempt(node_client, job, clock)
        delays.append((job.next_attempt_at - clock.now).total_seconds())

    assert delays == [60, 300, 1800, 3600, 3600, 3600]
    assert (job.state, job.error, job.attempt) == (HookJobState.PENDING, "The database is busy", 6)
    assert job.first_attempt_at == START
    assert not PluginActivityEvent.objects.filter(action=ActivityAction.ORG_REMOVED_HOOK_FAILED).exists()
    purging_grant.refresh_from_db()
    assert purging_grant.state == GrantState.PURGING


def test_after_the_window_the_job_fails_for_good_once(job, node_client, clock, log_messages):
    job = _attempt(node_client, job, clock)
    clock.now = START + timedelta(seconds=ORG_REMOVED_RETRY_WINDOW_SECONDS)

    job = _attempt(node_client, job, clock)

    assert (job.state, job.finished_at, job.attempt) == (HookJobState.FAILED, clock.now, 2)
    [event] = PluginActivityEvent.objects.filter(action=ActivityAction.ORG_REMOVED_HOOK_FAILED)
    assert event.detail == {"job_id": job.pk, "attempt": 2, "error": "The database is busy"}
    assert any(message.startswith("plugins.hook.gave_up") and f"job={job.pk}" in message for message in log_messages)
    assert _claim(node_client, job).status_code == 409


def test_an_overdue_attempt_counts_as_a_failed_one(job, node_client, clock):
    assert _claim(node_client, job).status_code == 200
    job.refresh_from_db()
    clock.now = job.deadline_at + timedelta(seconds=121)

    assert HookJobService().fail_overdue() == 1

    job.refresh_from_db()
    assert (job.state, job.error) == (HookJobState.PENDING, "The plugin node reported no result in time")
    assert job.next_attempt_at == clock.now + timedelta(seconds=60)


# ---- what a SuperAdmin may do ----


@pytest.mark.parametrize(
    ("state", "next_attempt_in", "expected"),
    [
        (HookJobState.PENDING, timedelta(minutes=5), ["retry", "skip"]),
        (HookJobState.PENDING, timedelta(0), ["skip"]),
        (HookJobState.PENDING, None, ["skip"]),
        (HookJobState.FAILED, None, ["retry", "skip"]),
        (HookJobState.RUNNING, None, []),
        (HookJobState.SUCCEEDED, None, []),
        (HookJobState.SKIPPED, None, []),
    ],
)
def test_the_allowed_actions_of_each_state(job, clock, state, next_attempt_in, expected):
    job.state = state
    job.next_attempt_at = clock.now + next_attempt_in if next_attempt_in is not None else None

    assert [action.value for action in allowed_org_removed_job_actions(job, clock.now)] == expected


def _retry(superadmin_client, job, identifier="weather"):
    return superadmin_client.post(f"/api/admin/plugins/{identifier}/org-removed-jobs/{job.pk}/retry/")


def _skip(superadmin_client, job, identifier="weather"):
    return superadmin_client.post(f"/api/admin/plugins/{identifier}/org-removed-jobs/{job.pk}/skip/")


@pytest.fixture
def committed(django_capture_on_commit_callbacks):
    """Run `call` and the callbacks its transaction leaves for after commit, as a request does."""

    def _run(call):
        with django_capture_on_commit_callbacks(execute=True):
            return call()

    return _run


def test_a_retry_starts_a_new_window_at_the_next_claim(job, node_client, clock, superadmin_client, log_messages, committed):
    job = _attempt(node_client, job, clock)
    clock.now = START + timedelta(seconds=ORG_REMOVED_RETRY_WINDOW_SECONDS)
    job = _attempt(node_client, job, clock)

    response = committed(lambda: _retry(superadmin_client, job))

    assert response.status_code == 202, response.content
    body = response.json()
    assert (body["state"], body["next_attempt_at"], body["first_attempt_at"], body["error"]) == (
        "pending",
        None,
        None,
        "The database is busy",
    )
    assert body["allowed_actions"] == ["skip"]
    job = _attempt(node_client, job, clock)
    assert (job.state, job.first_attempt_at) == (HookJobState.PENDING, clock.now)
    event = PluginActivityEvent.objects.get(action=ActivityAction.ORG_REMOVED_HOOK_RETRIED)
    assert (event.actor_kind, event.detail) == ("superadmin", {"job_id": job.pk})
    assert any(message.startswith("plugins.hook.retried") for message in log_messages)


@pytest.mark.parametrize("state", [HookJobState.PENDING, HookJobState.FAILED])
def test_a_waiting_or_failed_job_can_be_skipped(job, superadmin_client, clock, state, log_messages, committed):
    PluginHookJob.objects.filter(pk=job.pk).update(state=state)

    response = committed(lambda: _skip(superadmin_client, job))

    assert response.status_code == 200, response.content
    assert (response.json()["state"], response.json()["allowed_actions"]) == ("skipped", [])
    job.refresh_from_db()
    assert (job.state, job.finished_at) == (HookJobState.SKIPPED, clock.now)
    event = PluginActivityEvent.objects.get(action=ActivityAction.ORG_REMOVED_HOOK_SKIPPED)
    assert (event.actor_kind, event.detail) == ("superadmin", {"job_id": job.pk, "state_before": state})
    assert any(message.startswith("plugins.hook.skipped") for message in log_messages)


@pytest.mark.parametrize("state", [HookJobState.RUNNING, HookJobState.SUCCEEDED, HookJobState.SKIPPED])
def test_a_running_or_finished_job_can_be_neither_retried_nor_skipped(job, superadmin_client, state):
    PluginHookJob.objects.filter(pk=job.pk).update(state=state)

    retried = _retry(superadmin_client, job)
    skipped = _skip(superadmin_client, job)

    assert (retried.status_code, retried.json()["code"]) == (409, "org_removed_hook_not_retryable")
    assert (skipped.status_code, skipped.json()["code"]) == (409, "org_removed_hook_not_skippable")
    job.refresh_from_db()
    assert job.state == state


def test_a_due_job_cannot_be_retried(job, superadmin_client):
    assert _retry(superadmin_client, job).json()["code"] == "org_removed_hook_not_retryable"


def test_another_plugin_s_or_kind_s_job_is_not_found(job, superadmin_client, running_plugin, weather, acme):
    running_plugin(id="forecast", name="Forecast")
    install_job = PluginHookJob.objects.create(
        plugin=weather, organization_id=acme.pk, kind=HookJobKind.INSTALL, timeout_seconds=60
    )

    for response in (
        _skip(superadmin_client, job, identifier="forecast"),
        _retry(superadmin_client, install_job),
        _skip(superadmin_client, PluginHookJob(pk=job.pk + 1000)),
    ):
        assert (response.status_code, response.json()["code"]) == (404, "hook_job_not_found")
    assert _skip(superadmin_client, job, identifier="nothing").json()["code"] == "plugin_not_found"


def test_an_org_admin_or_an_api_key_gets_403(job, client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    assert _skip(client, job).status_code == 403
    assert client.get("/api/admin/plugins/weather/org-removed-jobs/").status_code == 403


# ---- the list ----


def test_the_list_shows_open_jobs_of_deleted_organizations_by_their_name(
    job, superadmin_client, weather, beta, acme, purging_grant
):
    finished = _ensure(weather, beta)
    PluginHookJob.objects.filter(pk=finished.pk).update(state=HookJobState.SUCCEEDED)
    beta_name, beta_id = beta.name, beta.pk
    beta.delete()

    open_jobs = superadmin_client.get("/api/admin/plugins/weather/org-removed-jobs/").json()
    deleted = superadmin_client.get(
        "/api/admin/plugins/weather/org-removed-jobs/?state=all&deleted_organizations=true&page_size=20"
    ).json()
    finished_page = superadmin_client.get("/api/admin/plugins/weather/org-removed-jobs/?state=finished").json()

    assert [row["id"] for row in open_jobs["results"]] == [job.pk]
    assert open_jobs["results"][0]["organization"] == {"id": acme.pk, "name": acme.name, "exists": True}
    assert open_jobs["results"][0]["grant_id"] == purging_grant.pk
    assert [row["organization"] for row in deleted["results"]] == [{"id": beta_id, "name": beta_name, "exists": False}]
    assert [row["id"] for row in finished_page["results"]] == [finished.pk]


def test_the_list_of_an_unknown_plugin_is_not_found(superadmin_client, plugins_enabled):
    response = superadmin_client.get("/api/admin/plugins/nothing/org-removed-jobs/")

    assert (response.status_code, response.json()["code"]) == (404, "plugin_not_found")


def test_the_retry_window_ends_seven_days_after_the_first_attempt(job, node_client, clock, superadmin_client):
    _attempt(node_client, job, clock)

    [row] = superadmin_client.get("/api/admin/plugins/weather/org-removed-jobs/").json()["results"]

    assert row["retry_until"] == (START + timedelta(days=7)).isoformat().replace("+00:00", "Z")
