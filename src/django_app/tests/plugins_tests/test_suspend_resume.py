"""Suspending a plugin in one organization, and resuming it."""

import threading
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from plugins.access.people_service import PluginPeopleService
from plugins.exceptions import GrantNotSuspendableError, OnBehalfOfNotAllowedError
from plugins.identity.plugin_login_tokens import issue_plugin_login_token
from plugins.lifecycle.grant_service import PluginGrantService
from plugins.lifecycle.suspended_run_stopper import SuspendedRunStopper
from plugins.lifecycle.suspension_service import SUSPENDED_BEFORE_HOOK_FINISHED, PluginSuspensionService
from plugins.models import (
    GrantState,
    HookJobState,
    PluginActivityEvent,
    PluginGrant,
    PluginHookJob,
    PluginRolePermission,
    PluginServiceAccount,
    PluginServiceAccountKey,
)
from rbac.models.enums import Permission
from rest_framework.test import APIClient
from tables.models import Session
from tables.services.session_manager_service import SessionManagerService

from tests.plugins_tests.conftest import GATEWAY_SECRET, service_account_client
from tests.plugins_tests.suspension_helpers import flow, own, set_state

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

FROZEN_NOW = datetime(2026, 10, 21, 12, 0, tzinfo=dt_timezone.utc)
ME_URL = "/api/plugin-runtime/me/"
DESIRED_STATE_URL = "/api/plugin-nodes/self/desired-state/"
SERVICE_ACCOUNTS_URL = "/api/plugins/service-accounts/"
AVAILABLE_URL = "/api/plugins/available/"
ROWS_URL = "/api/admin/plugin-role-permissions/rows/"


def _url(grant_id, action, identifier="weather"):
    return f"/api/admin/plugins/{identifier}/grants/{grant_id}/{action}/"


def _suspend(superadmin_client, grant):
    return superadmin_client.post(_url(grant.pk, "suspend"))


def _resume(superadmin_client, grant):
    return superadmin_client.post(_url(grant.pk, "resume"))


def _credentials(node_client, plugin):
    response = node_client.post(f"/api/plugin-nodes/self/placements/{plugin.placement.pk}/runtime-credentials/")
    assert response.status_code == 200, response.content
    return response.json()


def _org_client(client_as, user, organization):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(organization.pk))
    return client


@pytest.fixture
def weather(weather_backend):
    return weather_backend()


@pytest.fixture
def grant(weather, superadmin, acme):
    return PluginGrantService().grant("weather", acme.pk, superadmin)


@pytest.fixture
def hooked_weather(weather_backend):
    return weather_backend(hooks={"install": True})


@pytest.fixture
def installing_grant(hooked_weather, superadmin, acme):
    """Weather granted to Acme while its install hook has not run yet."""
    return PluginGrantService().grant("weather", acme.pk, superadmin)


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: FROZEN_NOW)
    return FROZEN_NOW


@pytest.fixture
def stopped_sessions(monkeypatch):
    """The sessions the stopper publishes a stop for; Redis is never reached."""
    stopped = []

    def publish_stop_session(session_id):
        stopped.append(session_id)
        return 1

    monkeypatch.setattr(SessionManagerService().redis_service, "publish_stop_session", publish_stop_session)
    return stopped


# ---- suspend ----


def test_suspending_keeps_the_data_for_the_grace_period(grant, superadmin_client, frozen_clock, settings):
    settings.PLUGINS_GRACE_PERIOD_DAYS = "7"

    response = _suspend(superadmin_client, grant)

    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["state"], body["allowed_actions"], body["suspension_cause"]) == ("suspended", ["resume", "purge"], "grant")
    grant.refresh_from_db()
    assert grant.state == GrantState.SUSPENDED
    assert grant.suspended_at == frozen_clock
    assert grant.purge_after == frozen_clock + timedelta(days=7)
    assert body["purge_after"] == "2026-10-28T12:00:00Z"


def test_suspending_revokes_every_key_including_one_in_its_overlap_and_keeps_the_account(
    weather, grant, service_account_key, superadmin_client, acme
):
    superseded = service_account_key(weather, acme)
    current = service_account_key(weather, acme)
    assert service_account_client(superseded, acme).get(ME_URL).status_code == 200

    _suspend(superadmin_client, grant)

    assert not PluginServiceAccountKey.objects.filter(service_account__grant=grant, revoked_at__isnull=True).exists()
    assert PluginServiceAccount.objects.filter(grant=grant, revoked_at__isnull=True).exists()
    for raw_key in (superseded, current):
        assert service_account_client(raw_key, acme).get(ME_URL).status_code == 401


def test_suspending_during_the_install_fails_the_pending_hook(installing_grant, superadmin_client):
    response = _suspend(superadmin_client, installing_grant)

    assert response.status_code == 200
    job = PluginHookJob.objects.get(grant=installing_grant)
    assert (job.state, job.error) == (HookJobState.FAILED, SUSPENDED_BEFORE_HOOK_FINISHED)
    assert job.finished_at is not None
    installing_grant.refresh_from_db()
    assert installing_grant.last_hook_error == SUSPENDED_BEFORE_HOOK_FINISHED
    assert response.json()["install_hook"]["state"] == "failed"


def test_suspending_while_the_hook_runs_fails_the_running_job(installing_grant, superadmin_client, node_client):
    job = PluginHookJob.objects.get(grant=installing_grant)
    assert node_client.post(f"/api/plugin-nodes/self/hook-jobs/{job.pk}/claim/").status_code == 200

    _suspend(superadmin_client, installing_grant)

    job.refresh_from_db()
    assert (job.state, job.error) == (HookJobState.FAILED, SUSPENDED_BEFORE_HOOK_FINISHED)


def test_suspending_is_recorded_and_logged(
    grant, superadmin_client, superadmin_user, acme, log_messages, frozen_clock, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        _suspend(superadmin_client, grant)

    event = PluginActivityEvent.objects.get(action="grant_suspended")
    assert (event.plugin_identifier, event.organization_id, event.actor_kind) == ("weather", acme.pk, "superadmin")
    assert (event.actor_user_id, event.actor_label) == (superadmin_user.pk, superadmin_user.email)
    assert event.detail == {"previous_state": "active", "purge_after": "2026-11-20T12:00:00Z", "cause": "grant"}
    assert (
        f"plugins.grant.suspended actor={superadmin_user.email} (id {superadmin_user.pk}) plugin=weather "
        f"grant={grant.pk} org={acme.pk} previous_state=active purge_after=2026-11-20T12:00:00+00:00 cause=grant"
    ) in log_messages


def test_once_committed_the_running_sessions_of_affected_flows_are_stopped(
    weather, grant, superadmin, acme, beta, stopped_sessions, django_capture_on_commit_callbacks, log_messages
):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    plain = flow(acme, "Plain")
    beta_grant = PluginGrantService().grant("weather", beta.pk, superadmin)
    beta_forecast = flow(beta, "Weather forecast")
    own(beta_forecast, beta_grant)
    running = Session.objects.create(graph=forecast, status=Session.SessionStatus.RUN)
    waiting = Session.objects.create(graph=forecast, status=Session.SessionStatus.WAIT_FOR_USER)
    pending = Session.objects.create(graph=forecast, status=Session.SessionStatus.PENDING)
    Session.objects.create(graph=forecast, status=Session.SessionStatus.END)
    Session.objects.create(graph=plain, status=Session.SessionStatus.RUN)
    Session.objects.create(graph=beta_forecast, status=Session.SessionStatus.RUN)

    with django_capture_on_commit_callbacks(execute=True):
        PluginSuspensionService().suspend("weather", grant.pk, superadmin)

    assert sorted(stopped_sessions) == sorted([running.pk, waiting.pk, pending.pk])
    assert f"plugins.grant.sessions_stopped plugin=weather grant={grant.pk} org={acme.pk} count=3 failed=0" in log_messages


def test_a_session_that_cannot_be_stopped_is_logged_and_the_others_still_stop(
    grant, superadmin, acme, monkeypatch, django_capture_on_commit_callbacks, log_messages
):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    broken = Session.objects.create(graph=forecast, status=Session.SessionStatus.RUN)
    healthy = Session.objects.create(graph=forecast, status=Session.SessionStatus.RUN)
    stopped = []

    def publish_stop_session(session_id):
        if session_id == broken.pk:
            raise ConnectionError("Redis is down")
        stopped.append(session_id)
        return 1

    monkeypatch.setattr(SessionManagerService().redis_service, "publish_stop_session", publish_stop_session)

    with django_capture_on_commit_callbacks(execute=True):
        PluginSuspensionService().suspend("weather", grant.pk, superadmin)

    assert stopped == [healthy.pk]
    assert f"plugins.grant.sessions_stopped plugin=weather grant={grant.pk} org={acme.pk} count=1 failed=1" in log_messages


def test_a_stopper_that_fails_leaves_the_suspension_committed_and_logged(
    grant, superadmin, superadmin_client, monkeypatch, django_capture_on_commit_callbacks, log_messages
):
    def broken_stop_for(self, **kwargs):
        raise RuntimeError("the session index is unavailable")

    monkeypatch.setattr(SuspendedRunStopper, "stop_for", broken_stop_for)

    with django_capture_on_commit_callbacks(execute=True):
        response = _suspend(superadmin_client, grant)

    assert response.status_code == 200
    grant.refresh_from_db()
    assert grant.state == GrantState.SUSPENDED
    assert any(message.startswith("plugins.grant.suspended") for message in log_messages)


def test_the_suspension_is_logged_before_the_sessions_are_stopped(
    grant, superadmin, monkeypatch, django_capture_on_commit_callbacks, log_messages
):
    seen_when_stopping = []

    def stop_for(self, **kwargs):
        seen_when_stopping.extend(message.split(" ")[0] for message in log_messages)

    monkeypatch.setattr(SuspendedRunStopper, "stop_for", stop_for)

    with django_capture_on_commit_callbacks(execute=True):
        PluginSuspensionService().suspend("weather", grant.pk, superadmin)

    assert "plugins.grant.suspended" in seen_when_stopping


def _queries_of_stopping(weather, superadmin, organization, session_count):
    grant = set_state(PluginGrantService().grant("weather", organization.pk, superadmin), GrantState.SUSPENDED)
    for number in range(session_count):
        forecast = flow(organization, f"Weather forecast {session_count}-{number}")
        own(forecast, grant)
        Session.objects.create(graph=forecast, status=Session.SessionStatus.RUN)
    stopper = SuspendedRunStopper()
    with CaptureQueriesContext(connection) as captured:
        stopper.stop_for(organization_id=organization.pk, grant_id=grant.pk, plugin_identifier="weather")
    return len(captured.captured_queries)


def test_stopping_costs_the_same_queries_for_three_sessions_and_for_thirty(
    weather, superadmin, acme, beta, stopped_sessions
):
    few = _queries_of_stopping(weather, superadmin, acme, 3)
    many = _queries_of_stopping(weather, superadmin, beta, 30)

    assert len(stopped_sessions) == 33
    assert few == many


def test_nothing_is_stopped_before_the_suspension_commits(grant, superadmin, acme, stopped_sessions):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    Session.objects.create(graph=forecast, status=Session.SessionStatus.RUN)

    PluginSuspensionService().suspend("weather", grant.pk, superadmin)

    assert stopped_sessions == []


# ---- what a suspension stops without code of its own ----


def test_the_organization_leaves_the_runtime_file_and_the_credentials_revision_changes(
    weather, grant, superadmin, superadmin_client, node_client, acme, beta
):
    PluginGrantService().grant("weather", beta.pk, superadmin)
    before = node_client.get(DESIRED_STATE_URL).json()["placements"][0]["credentials_revision"]

    _suspend(superadmin_client, grant)

    after = node_client.get(DESIRED_STATE_URL).json()["placements"][0]["credentials_revision"]
    assert after != before
    assert set(_credentials(node_client, weather)["runtime_file"]["service_accounts"]) == {str(beta.pk)}


def test_people_lose_the_plugin_page_and_the_service_account_card_says_suspended(
    grant, superadmin_client, client_as, member_only, admin_acme, acme
):
    assert [plugin["identifier"] for plugin in _org_client(client_as, member_only, acme).get(AVAILABLE_URL).json()] == ["weather"]

    _suspend(superadmin_client, grant)

    assert _org_client(client_as, member_only, acme).get(AVAILABLE_URL).json() == []
    [card] = _org_client(client_as, admin_acme, acme).get(SERVICE_ACCOUNTS_URL).json()
    assert card["grant_state"] == "suspended"


def test_the_plugin_can_no_longer_act_for_a_person(grant, superadmin_client, member_only):
    _suspend(superadmin_client, grant)
    grant.refresh_from_db()

    with pytest.raises(OnBehalfOfNotAllowedError):
        PluginPeopleService().on_behalf_of(grant, member_only.pk)


@pytest.mark.usefixtures("gateway_in_request_thread")
def test_a_person_s_plugin_login_is_refused_once_the_gateway_s_person_cache_expires(
    grant, superadmin_client, member_only, acme, anonymous_client, settings, clean_login_state
):
    settings.PLUGINS_GATEWAY_SECRET = GATEWAY_SECRET
    token = issue_plugin_login_token(user=member_only, org_id=acme.pk, grant_id=grant.pk, identifier="weather").token

    def check():
        return anonymous_client.get(
            "/api/plugin-gateway/check/",
            HTTP_X_PLUGIN_GATEWAY_SECRET=GATEWAY_SECRET,
            HTTP_X_PLUGIN_IDENTIFIER="weather",
            HTTP_X_ORIGINAL_METHOD="GET",
            HTTP_X_ORIGINAL_URI="/api/whoami",
            HTTP_X_ORIGINAL_NORMALIZED_PATH="/api/whoami",
            HTTP_X_REAL_IP="203.0.113.7",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    assert check().status_code == 200
    _suspend(superadmin_client, grant)
    # The gateway keeps a person's decision for 10 seconds; once it expires the login is refused.
    cache.delete_pattern("plugins:gw:person:*")

    assert check().status_code == 401


def _matrix_rows(client_as, admin_acme, acme):
    return [row["plugin_identifier"] for row in client_as(admin_acme).get(ROWS_URL, {"org_id": acme.pk}).json()["rows"]]


def _role_actions(client_as, admin_acme, role):
    response = client_as(admin_acme).get(f"/api/admin/plugin-role-permissions/{role.pk}/")
    return {row["plugin_identifier"]: row["granted"] for row in response.json()["rows"]}


def test_the_roles_matrix_hides_the_plugin_and_shows_it_again_with_the_same_actions_on_resume(
    grant, superadmin_client, client_as, admin_acme, acme, make_custom_role
):
    forecasters = make_custom_role(acme, "Forecasters")
    PluginRolePermission.objects.create(grant=grant, role=forecasters, permissions=int(Permission.READ))
    assert _matrix_rows(client_as, admin_acme, acme) == ["weather"]

    _suspend(superadmin_client, grant)

    assert _matrix_rows(client_as, admin_acme, acme) == []
    assert PluginRolePermission.objects.filter(grant=grant, role=forecasters).exists()

    _resume(superadmin_client, grant)

    assert _matrix_rows(client_as, admin_acme, acme) == ["weather"]
    assert _role_actions(client_as, admin_acme, forecasters) == {"weather": ["read"]}


def test_a_suspended_grant_gets_no_install_job_in_the_desired_state(installing_grant, superadmin_client, node_client):
    assert node_client.get(DESIRED_STATE_URL).json()["placements"][0]["hook_jobs"] != []

    _suspend(superadmin_client, installing_grant)

    assert node_client.get(DESIRED_STATE_URL).json()["placements"][0]["hook_jobs"] == []


def test_a_suspended_grant_is_not_counted_and_granting_again_conflicts(grant, superadmin_client, acme):
    _suspend(superadmin_client, grant)

    assert superadmin_client.get("/api/admin/plugins/weather/").json()["grant_count"] == 0
    response = superadmin_client.post("/api/admin/plugins/weather/grants/", {"organization_id": acme.pk}, format="json")
    assert (response.status_code, response.json()["code"]) == (409, "plugin_already_granted")


def test_suspending_twice_conflicts(grant, superadmin_client):
    _suspend(superadmin_client, grant)

    response = _suspend(superadmin_client, grant)

    assert (response.status_code, response.json()["code"]) == (409, "grant_not_suspendable")


def test_resuming_an_active_grant_conflicts(grant, superadmin_client):
    response = _resume(superadmin_client, grant)

    assert (response.status_code, response.json()["code"]) == (409, "grant_not_suspended")


@pytest.mark.parametrize("action", ["suspend", "resume"])
def test_an_unknown_grant_or_one_of_another_plugin_is_not_found(grant, superadmin_client, running_plugin, action):
    running_plugin(id="almanac", name="Almanac")

    for url in (_url(grant.pk + 1000, action), _url(grant.pk, action, identifier="almanac"), _url(grant.pk, action, identifier="missing")):
        response = superadmin_client.post(url)
        assert (response.status_code, response.json()["code"]) == (404, "grant_not_found"), url


@pytest.mark.parametrize("action", ["suspend", "resume"])
def test_an_org_admin_is_refused(grant, client_as, admin_acme, acme, action):
    response = _org_client(client_as, admin_acme, acme).post(_url(grant.pk, action))

    assert response.status_code == 403
    assert PluginGrant.objects.get(pk=grant.pk).state == GrantState.ACTIVE


@pytest.mark.parametrize("action", ["suspend", "resume"])
def test_an_api_key_is_refused_even_a_superadmin_s(grant, issue_api_key, superadmin_user, action):
    raw_key, _ = issue_api_key(user=superadmin_user)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    assert client.post(_url(grant.pk, action)).status_code == 403


# ---- resume ----


def test_resuming_makes_the_grant_active_again(grant, superadmin_client, superadmin_user, acme, log_messages):
    _suspend(superadmin_client, grant)

    response = _resume(superadmin_client, grant)

    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["state"], body["suspended_at"], body["purge_after"]) == ("active", None, None)
    assert (body["allowed_actions"], body["suspension_cause"]) == (["suspend", "purge"], None)
    event = PluginActivityEvent.objects.get(action="grant_resumed")
    assert (event.organization_id, event.actor_user_id, event.detail) == (acme.pk, superadmin_user.pk, {"state": "active", "cause": "grant"})
    assert (
        f"plugins.grant.resumed actor={superadmin_user.email} (id {superadmin_user.pk}) plugin=weather "
        f"grant={grant.pk} org={acme.pk} state=active"
    ) in log_messages


def test_resuming_revokes_a_key_minted_during_the_suspension_and_the_next_fetch_mints_a_working_one(
    weather, grant, service_account_key, superadmin_client, node_client, acme
):
    old_key = service_account_key(weather, acme)
    _suspend(superadmin_client, grant)
    # A key minted by a credentials call that read the grant just before the suspension
    # committed.
    concurrent = PluginServiceAccountKey.objects.create(
        service_account=grant.service_account, prefix="esp-concurre", key_hash="c" * 64
    )

    _resume(superadmin_client, grant)

    concurrent.refresh_from_db()
    assert concurrent.revoked_at is not None
    new_key = _credentials(node_client, weather)["runtime_file"]["service_accounts"][str(acme.pk)]["key"]
    assert service_account_client(new_key, acme).get(ME_URL).status_code == 200
    assert service_account_client(old_key, acme).get(ME_URL).status_code == 401


def test_after_resuming_the_plugin_s_flows_run_again(grant, superadmin_client, client_as, admin_acme, acme, redis_client_mock):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    olga = _org_client(client_as, admin_acme, acme)
    _suspend(superadmin_client, grant)
    assert olga.post(reverse("run-session"), {"graph_id": forecast.pk, "variables": {}}, format="json").status_code == 409

    _resume(superadmin_client, grant)

    assert olga.post(reverse("run-session"), {"graph_id": forecast.pk, "variables": {}}, format="json").status_code == 201


def test_a_pending_install_is_given_up_by_suspending_and_resuming_then_retried(
    installing_grant, superadmin_client, node_client
):
    # A pending install hook waits for the plugin for as long as it takes; this is the way out.
    _suspend(superadmin_client, installing_grant)

    resumed = _resume(superadmin_client, installing_grant).json()

    assert resumed["state"] == "install_failed"
    assert resumed["allowed_actions"] == ["retry_install", "suspend", "purge"]
    assert resumed["last_hook_error"] == SUSPENDED_BEFORE_HOOK_FINISHED
    retried = superadmin_client.post(_url(installing_grant.pk, "retry-hook"))
    assert retried.status_code == 202, retried.content
    assert retried.json()["state"] == "granting"
    job = PluginHookJob.objects.get(grant=installing_grant)
    assert job.state == HookJobState.PENDING
    assert [listed["job_id"] for listed in node_client.get(DESIRED_STATE_URL).json()["placements"][0]["hook_jobs"]] == [job.pk]


def test_a_grant_suspended_after_its_install_succeeded_resumes_active(installing_grant, superadmin_client, node_client):
    job = PluginHookJob.objects.get(grant=installing_grant)
    node_client.post(f"/api/plugin-nodes/self/hook-jobs/{job.pk}/claim/")
    result = node_client.post(
        f"/api/plugin-nodes/self/hook-jobs/{job.pk}/result/",
        {"attempt": 1, "outcome": "succeeded", "duration_ms": 10},
        format="json",
    )
    assert result.status_code == 204, result.content
    _suspend(superadmin_client, installing_grant)

    assert _resume(superadmin_client, installing_grant).json()["state"] == "active"


# ---- concurrency ----


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_suspensions_give_one_suspension_and_one_conflict(weather, superadmin, acme):
    grant = PluginGrantService().grant("weather", acme.pk, superadmin)
    start = threading.Barrier(2)
    outcomes = []

    def suspend():
        try:
            start.wait()
            PluginSuspensionService().suspend("weather", grant.pk, superadmin)
            outcomes.append("suspended")
        except GrantNotSuspendableError:
            outcomes.append("conflict")
        finally:
            connection.close()

    threads = [threading.Thread(target=suspend) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["conflict", "suspended"]
    assert PluginActivityEvent.objects.filter(action="grant_suspended").count() == 1
