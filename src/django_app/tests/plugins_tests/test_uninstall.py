"""Uninstalling a plugin, and reinstalling it within its grace period."""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.utils import timezone
from plugins.lifecycle.grant_service import PluginGrantService
from plugins.lifecycle.org_removed_hooks import OrgRemovedHookService
from plugins.lifecycle.suspension_service import SUSPENDED_BEFORE_HOOK_FINISHED, PluginSuspensionService
from plugins.models import (
    ActivityAction,
    GrantState,
    HookJobKind,
    HookJobState,
    Plugin,
    PluginActivityEvent,
    PluginGrant,
    PluginHookJob,
    PluginServiceAccountKey,
    PluginState,
    SuspensionCause,
)
from tables.models import Session
from tables.services.session_manager_service import SessionManagerService

from tests.plugins_tests.conftest import GATEWAY_SECRET, mark_running, upload_file
from tests.plugins_tests.package_builder import backend_manifest, build_package
from tests.plugins_tests.suspension_helpers import flow, own

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root", "gateway_in_request_thread"),
]

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=dt_timezone.utc)
DESIRED_STATE_URL = "/api/plugin-nodes/self/desired-state/"
HOOKS = {"install": True, "org_removed": True}


@pytest.fixture(autouse=True)
def gateway_secret(settings):
    settings.PLUGINS_GATEWAY_SECRET = GATEWAY_SECRET
    settings.PLUGINS_GRACE_PERIOD_DAYS = "30"


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: NOW)
    return NOW


@pytest.fixture
def weather(weather_backend):
    return weather_backend(hooks=HOOKS)


@pytest.fixture
def grants(weather, superadmin, acme, beta, make_organization):
    """Acme active, Beta still installing, Cobalt suspended on its own a week ago."""
    acme_grant = PluginGrantService().grant("weather", acme.pk, superadmin)
    PluginHookJob.objects.filter(grant=acme_grant).update(state=HookJobState.SUCCEEDED)
    PluginGrant.objects.filter(pk=acme_grant.pk).update(state=GrantState.ACTIVE)
    beta_grant = PluginGrantService().grant("weather", beta.pk, superadmin)
    cobalt = make_organization("Cobalt")
    cobalt_grant = PluginGrantService().grant("weather", cobalt.pk, superadmin)
    PluginHookJob.objects.filter(grant=cobalt_grant).update(state=HookJobState.SUCCEEDED)
    PluginGrant.objects.filter(pk=cobalt_grant.pk).update(
        state=GrantState.SUSPENDED,
        suspension_cause=SuspensionCause.GRANT,
        suspended_at=NOW - timedelta(days=7),
        purge_after=NOW + timedelta(days=23),
    )
    return {
        "acme": PluginGrant.objects.get(pk=acme_grant.pk),
        "beta": PluginGrant.objects.get(pk=beta_grant.pk),
        "cobalt": PluginGrant.objects.get(pk=cobalt_grant.pk),
    }


@pytest.fixture
def make_organization(db):
    from rbac.models import Organization

    def _make(name):
        return Organization.objects.create(name=name)

    return _make


@pytest.fixture
def stopped_sessions(monkeypatch):
    stopped = []
    monkeypatch.setattr(
        SessionManagerService().redis_service, "publish_stop_session", lambda session_id: stopped.append(session_id) or 1
    )
    return stopped


def _uninstall(client, identifier="weather"):
    return client.post(f"/api/admin/plugins/{identifier}/uninstall/")


def _reinstall(client, identifier="weather"):
    return client.post(f"/api/admin/plugins/{identifier}/reinstall/")


@pytest.fixture
def committed(django_capture_on_commit_callbacks):
    """Run `call` and the callbacks its transaction leaves for after commit, as a request does."""

    def _run(call):
        with django_capture_on_commit_callbacks(execute=True):
            return call()

    return _run


def _check(client, uri):
    return client.get(
        "/api/plugin-gateway/check/",
        HTTP_X_PLUGIN_GATEWAY_SECRET=GATEWAY_SECRET,
        HTTP_X_PLUGIN_IDENTIFIER="weather",
        HTTP_X_ORIGINAL_METHOD="GET",
        HTTP_X_ORIGINAL_URI=uri,
        HTTP_X_ORIGINAL_NORMALIZED_PATH=uri,
        HTTP_X_ORIGINAL_CONTENT_LENGTH="",
        HTTP_X_ORIGINAL_TRANSFER_ENCODING="",
        HTTP_X_REAL_IP="203.0.113.7",
    )


def _placement(node_client):
    [placement] = node_client.get(DESIRED_STATE_URL).json()["placements"]
    return placement


# ---- uninstall ----


def test_uninstall_suspends_every_grant_in_service_until_the_plugin_s_date(
    grants, superadmin_client, frozen_clock, log_messages, committed, stopped_sessions
):
    response = committed(lambda: _uninstall(superadmin_client))

    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["state"], body["allowed_actions"]) == ("uninstalling", ["reinstall", "purge"])
    assert body["uninstall_requested_at"] == "2026-10-21T12:00:00Z"
    assert body["purge_after"] == "2026-11-20T12:00:00Z"
    plugin = Plugin.objects.get(identifier="weather")
    for name in ("acme", "beta"):
        grant = PluginGrant.objects.get(pk=grants[name].pk)
        assert (grant.state, grant.suspension_cause, grant.suspended_at, grant.purge_after) == (
            GrantState.SUSPENDED,
            SuspensionCause.UNINSTALL,
            NOW,
            plugin.purge_after,
        )
    cobalt = PluginGrant.objects.get(pk=grants["cobalt"].pk)
    assert (cobalt.suspension_cause, cobalt.suspended_at, cobalt.purge_after) == (
        SuspensionCause.GRANT,
        NOW - timedelta(days=7),
        NOW + timedelta(days=23),
    )
    events = PluginActivityEvent.objects.filter(action=ActivityAction.GRANT_SUSPENDED)
    assert sorted(event.organization_id for event in events) == sorted([grants["acme"].org_id, grants["beta"].org_id])
    assert {event.detail["cause"] for event in events} == {"uninstall"}
    uninstalled = PluginActivityEvent.objects.get(action=ActivityAction.PLUGIN_UNINSTALLED)
    assert (uninstalled.organization_id, uninstalled.detail) == (
        None,
        {"purge_after": "2026-11-20T12:00:00Z", "organizations": 2},
    )
    assert any(message.startswith("plugins.plugin.uninstalled") and "grants=2" in message for message in log_messages)


def test_uninstall_fails_open_install_jobs_revokes_keys_and_stops_sessions_once_per_organization(
    grants, superadmin_client, service_account_key, weather, acme, beta, stopped_sessions, django_capture_on_commit_callbacks
):
    service_account_key(weather, acme)
    graph = flow(acme, "Weather forecast")
    own(graph, grants["acme"])
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.RUN)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        _uninstall(superadmin_client)

    install = PluginHookJob.objects.get(grant=grants["beta"], kind=HookJobKind.INSTALL)
    assert (install.state, install.error) == (HookJobState.FAILED, SUSPENDED_BEFORE_HOOK_FINISHED)
    assert not PluginServiceAccountKey.objects.filter(revoked_at__isnull=True).exists()
    assert stopped_sessions == [session.pk]
    stoppers = [
        callback for callback in callbacks if getattr(callback, "__qualname__", "").endswith("stop_affected_sessions")
    ]
    assert len(stoppers) == 2


def test_uninstalling_twice_is_refused(grants, superadmin_client):
    _uninstall(superadmin_client)

    response = _uninstall(superadmin_client)

    assert (response.status_code, response.json()["code"]) == (409, "plugin_not_uninstallable")


def test_an_unknown_plugin_is_not_found(superadmin_client):
    assert _uninstall(superadmin_client, "missing").json()["code"] == "plugin_not_found"
    assert _reinstall(superadmin_client, "missing").json()["code"] == "plugin_not_found"


def test_an_org_admin_cannot_uninstall(grants, client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    assert _uninstall(client).status_code == 403
    assert Plugin.objects.get(identifier="weather").state == PluginState.RUNNING


# ---- the node and the gateway while uninstalled ----


def test_an_uninstalled_plugin_is_stopped_with_no_service_accounts(grants, superadmin_client, node_client):
    _uninstall(superadmin_client)

    placement = _placement(node_client)
    assert (placement["desired_state"], placement["hook_jobs"]) == ("stopped", [])
    credentials = node_client.post(
        f"/api/plugin-nodes/self/placements/{placement['placement_id']}/runtime-credentials/"
    ).json()
    assert credentials["runtime_file"]["service_accounts"] == {}


def test_an_uninstalled_plugin_runs_only_while_an_organization_removed_hook_is_due_or_running(
    grants, superadmin_client, node_client, weather, acme
):
    _uninstall(superadmin_client)
    plugin = Plugin.objects.select_related("current_package").get(pk=weather.pk)
    job = OrgRemovedHookService().ensure_job(plugin, organization_id=acme.pk, organization_name=acme.name, grant=None)

    due = _placement(node_client)
    PluginHookJob.objects.filter(pk=job.pk).update(state=HookJobState.RUNNING)
    running = _placement(node_client)
    PluginHookJob.objects.filter(pk=job.pk).update(
        state=HookJobState.PENDING, next_attempt_at=timezone.now() + timedelta(minutes=5)
    )
    waiting = _placement(node_client)

    assert (due["desired_state"], [item["job_id"] for item in due["hook_jobs"]]) == ("running", [job.pk])
    assert running["desired_state"] == "running"
    assert (waiting["desired_state"], waiting["hook_jobs"]) == ("stopped", [])
    assert due["database"] == running["database"]


@pytest.mark.parametrize("uri", ["/api/ping", "/api/forecast", "/"])
def test_the_gateway_serves_no_path_of_an_uninstalled_plugin_from_the_moment_it_commits(
    grants, superadmin_client, anonymous_client, uri
):
    _check(anonymous_client, "/api/ping")  # the plugin's snapshot is now cached

    _uninstall(superadmin_client)

    response = _check(anonymous_client, uri)
    assert (response.status_code, response.headers.get("X-Plugin-Deny")) == (403, "not_found")


def test_a_report_never_moves_an_uninstalled_or_deleting_plugin(grants, superadmin_client, node_client, weather):
    _uninstall(superadmin_client)
    report = {
        "format": 1,
        "agent_version": "1.0.0",
        "reported_at": "2026-10-21T12:00:00Z",
        "placements": [
            {
                "placement_id": weather.placement.pk,
                "observed_state": "failed",
                "health": "failing",
                "restarts": 3,
                "observed_version": weather.current_package.version,
            }
        ],
    }

    for state in (PluginState.UNINSTALLING, PluginState.PURGING):
        Plugin.objects.filter(pk=weather.pk).update(state=state)
        for observed in ("failed", "running"):
            report["placements"][0].update(observed_state=observed, health="ok" if observed == "running" else "failing")
            assert node_client.post("/api/plugin-nodes/self/reports/", report, format="json").status_code == 204
            assert Plugin.objects.get(pk=weather.pk).state == state


# ---- what an uninstalled plugin refuses and allows ----


def test_upload_approve_and_restart_are_refused_while_uninstalled_or_deleting(
    grants, superadmin_client, weather, installation, superadmin
):
    _uninstall(superadmin_client)
    pending_package = weather.packages.create(
        version="9.9.9",
        sha256="0" * 64,
        size=1,
        storage_key="x",
        manifest=weather.current_package.manifest,
        trust="untrusted",
        signature_status="absent",
        icon_bytes=b"",
        icon_media_type="image/svg+xml",
    )
    data = build_package(manifest=backend_manifest(version="0.3.0", hooks=HOOKS))

    for state in (PluginState.UNINSTALLING, PluginState.PURGING):
        Plugin.objects.filter(pk=weather.pk).update(state=state)
        uploaded = superadmin_client.post("/api/admin/plugins/packages/", {"file": upload_file(data)}, format="multipart")
        approved = superadmin_client.post(f"/api/admin/plugins/packages/{pending_package.pk}/approve/", {}, format="json")
        restarted = superadmin_client.post("/api/admin/plugins/weather/restart/")
        for response in (uploaded, approved, restarted):
            assert (response.status_code, response.json()["code"]) == (409, "plugin_uninstalling"), response.content


def test_a_grant_is_refused_while_uninstalled(grants, superadmin_client, make_organization):
    _uninstall(superadmin_client)
    newcomer = make_organization("Newcomer")

    response = superadmin_client.post("/api/admin/plugins/weather/grants/", {"organization_id": newcomer.pk}, format="json")

    assert (response.status_code, response.json()["code"]) == (409, "plugin_not_running")


def test_settings_and_limits_stay_editable_while_uninstalled_but_not_while_deleting(grants, superadmin_client, weather):
    _uninstall(superadmin_client)
    settings_change = {"values": {"units": "imperial"}}
    limits_change = {"overrides": {"memory_mb": 128}}

    assert superadmin_client.patch("/api/admin/plugins/weather/settings/", settings_change, format="json").status_code == 200
    assert superadmin_client.patch("/api/admin/plugins/weather/limits/", limits_change, format="json").status_code == 200

    Plugin.objects.filter(pk=weather.pk).update(state=PluginState.PURGING)

    for response in (
        superadmin_client.patch("/api/admin/plugins/weather/settings/", settings_change, format="json"),
        superadmin_client.patch("/api/admin/plugins/weather/limits/", limits_change, format="json"),
    ):
        assert (response.status_code, response.json()["code"]) == (409, "plugin_uninstalling")


def test_grant_actions_other_than_purge_are_refused_while_uninstalled(grants, superadmin_client):
    _uninstall(superadmin_client)
    grant = grants["cobalt"]

    response = superadmin_client.post(f"/api/admin/plugins/weather/grants/{grant.pk}/resume/")

    assert (response.status_code, response.json()["code"]) == (409, "plugin_uninstalling")
    [row] = [
        row
        for row in superadmin_client.get("/api/admin/plugins/weather/grants/").json()["results"]
        if row["id"] == grant.pk
    ]
    assert row["allowed_actions"] == ["purge"]


# ---- reinstall ----


def test_reinstall_resumes_exactly_the_grants_the_uninstall_suspended(
    grants, superadmin_client, node_client, weather, log_messages, committed
):
    _uninstall(superadmin_client)

    response = committed(lambda: _reinstall(superadmin_client))

    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["state"], body["purge_after"], body["uninstall_requested_at"]) == ("provisioning", None, None)
    states = {name: PluginGrant.objects.get(pk=grant.pk) for name, grant in grants.items()}
    assert (states["acme"].state, states["acme"].suspension_cause, states["acme"].purge_after) == (GrantState.ACTIVE, None, None)
    assert states["beta"].state == GrantState.INSTALL_FAILED
    assert (states["cobalt"].state, states["cobalt"].suspension_cause) == (GrantState.SUSPENDED, SuspensionCause.GRANT)
    resumed = PluginActivityEvent.objects.filter(action=ActivityAction.GRANT_RESUMED)
    assert {event.detail["cause"] for event in resumed} == {"uninstall"}
    assert PluginActivityEvent.objects.get(action=ActivityAction.PLUGIN_REINSTALLED).detail == {"organizations_resumed": 2}
    assert any(message.startswith("plugins.plugin.reinstalled") for message in log_messages)

    mark_running(weather)
    assert _placement(node_client)["desired_state"] == "running"


def test_a_frontend_only_plugin_is_running_again_at_once(running_plugin, superadmin_client):
    running_plugin()
    _uninstall(superadmin_client)

    assert _reinstall(superadmin_client).json()["state"] == "running"


def test_reinstalling_a_plugin_that_is_not_uninstalled_is_refused(grants, superadmin_client):
    response = _reinstall(superadmin_client)

    assert (response.status_code, response.json()["code"]) == (409, "plugin_not_uninstalling")


def test_a_grant_suspended_on_its_own_after_the_uninstall_stays_suspended(grants, superadmin_client, superadmin):
    _uninstall(superadmin_client)
    _reinstall(superadmin_client)
    PluginSuspensionService().suspend("weather", grants["acme"].pk, superadmin)

    assert PluginGrant.objects.get(pk=grants["acme"].pk).suspension_cause == SuspensionCause.GRANT
