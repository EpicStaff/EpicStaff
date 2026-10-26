"""An open upgrade and the other lifecycle actions: uninstall, delete, restart, grants, runs."""

import pytest
from plugins.exceptions import PluginSuspendedError
from plugins.lifecycle.retention_service import RetentionService
from plugins.lifecycle.suspension_service import PluginSuspensionService
from plugins.models import (
    GrantState,
    HookJobKind,
    HookJobState,
    Plugin,
    PluginGrant,
    PluginHookJob,
    PluginState,
    PluginUpgrade,
    UpgradeStage,
)
from plugins.organization_deletion import ORGANIZATION_DELETED
from plugins.packages.spa_publisher import MAINTENANCE_FLAG
from plugins.runs.run_guard import PluginRunGuard
from rbac.governance.organizations import OrganizationManagementService
from rbac.models import Organization
from tables.models import Session
from tables.services.run_admission import RunKind, RunSubject
from tables.services.session_manager_service import SessionManagerService

from tests.plugins_tests.suspension_helpers import flow, own
from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    active_grant,
    advance_url,
    backup_body,
    newer,
    upgrade_jobs,
    upgrade_of,
    weather,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PLUGIN_URL = "/api/admin/plugins/weather/"


def _stage(node_client, upgrade, stage, capture):
    with capture(execute=True):
        node_client.post(advance_url(upgrade.pk), {"to": "maintenance"}, format="json")
    if stage == "migrating":
        node_client.post(advance_url(upgrade.pk), {"to": "migrations", "backup": backup_body(upgrade)}, format="json")
    upgrade.refresh_from_db()
    return upgrade


@pytest.fixture
def stopped_sessions(monkeypatch):
    stopped = []
    monkeypatch.setattr(
        SessionManagerService().redis_service, "publish_stop_session", lambda session_id: stopped.append(session_id) or 1
    )
    return stopped


# ---- uninstall and delete ----


@pytest.mark.parametrize("stage", ["preparing", "maintenance"])
def test_uninstall_is_refused_while_an_upgrade_is_open(
    weather, newer, upgrade_of, node_client, superadmin_client, django_capture_on_commit_callbacks, stage
):
    upgrade = upgrade_of(newer())
    if stage == "maintenance":
        _stage(node_client, upgrade, stage, django_capture_on_commit_callbacks)

    response = superadmin_client.post(f"{PLUGIN_URL}uninstall/")

    assert (response.status_code, response.json()["code"]) == (409, "plugin_upgrade_open")


def test_deleting_the_plugin_abandons_an_upgrade_still_being_prepared(
    weather, newer, upgrade_of, superadmin_client, django_capture_on_commit_callbacks
):
    upgrade = upgrade_of(newer())

    with django_capture_on_commit_callbacks(execute=True):
        response = superadmin_client.delete(PLUGIN_URL, {"verification_phrase": "purge-weather"}, format="json")

    assert response.status_code == 202, response.content
    upgrade.refresh_from_db()
    assert upgrade.stage == UpgradeStage.ABANDONED
    assert Plugin.objects.get(pk=weather.pk).current_package_id == weather.current_package_id


def test_deleting_a_plugin_in_maintenance_after_its_migrations_started_keeps_the_target(
    weather, newer, upgrade_of, node_client, superadmin_client, spa_root, django_capture_on_commit_callbacks
):
    upgrade = _stage(node_client, upgrade_of(newer()), "migrating", django_capture_on_commit_callbacks)
    PluginUpgrade.objects.filter(pk=upgrade.pk).update(failed_at=upgrade.started_at)
    assert (spa_root / "weather" / MAINTENANCE_FLAG).exists()

    with django_capture_on_commit_callbacks(execute=True):
        response = superadmin_client.delete(PLUGIN_URL, {"verification_phrase": "purge-weather"}, format="json")

    assert response.status_code == 202, response.content
    plugin = Plugin.objects.get(pk=weather.pk)
    assert (plugin.state, plugin.current_package_id) == (PluginState.PURGING, upgrade.to_package_id)
    assert PluginUpgrade.objects.get(pk=upgrade.pk).stage == UpgradeStage.ABANDONED
    assert not (spa_root / "weather" / MAINTENANCE_FLAG).exists()


# ---- restart ----


def test_a_restart_while_preparing_restarts_the_running_version(weather, newer, upgrade_of, superadmin_client):
    upgrade_of(newer())

    assert superadmin_client.post(f"{PLUGIN_URL}restart/").status_code == 202


def test_a_restart_in_maintenance_is_refused(weather, newer, upgrade_of, node_client, superadmin_client, django_capture_on_commit_callbacks):
    _stage(node_client, upgrade_of(newer()), "maintenance", django_capture_on_commit_callbacks)

    response = superadmin_client.post(f"{PLUGIN_URL}restart/")

    assert (response.status_code, response.json()["code"]) == (409, "plugin_upgrade_open")


# ---- grants ----


def test_an_organization_granted_while_the_upgrade_is_prepared_installs_on_the_running_version(
    weather, newer, upgrade_of, superadmin_client, acme
):
    upgrade_of(newer())

    response = superadmin_client.post(f"{PLUGIN_URL}grants/", {"organization_id": acme.pk}, format="json")

    assert response.status_code == 201
    assert (response.json()["state"], response.json()["installed_version"]) == ("active", "0.6.0")


def test_no_organization_is_granted_during_maintenance(
    weather, newer, upgrade_of, node_client, superadmin_client, acme, django_capture_on_commit_callbacks
):
    _stage(node_client, upgrade_of(newer()), "maintenance", django_capture_on_commit_callbacks)

    response = superadmin_client.post(f"{PLUGIN_URL}grants/", {"organization_id": acme.pk}, format="json")

    assert (response.status_code, response.json()["code"]) == (409, "plugin_not_running")


def test_in_maintenance_the_settings_follow_the_new_version(
    weather, newer, upgrade_of, node_client, superadmin_client, django_capture_on_commit_callbacks
):
    region = {"key": "region", "type": "string", "label": "Region", "description": "Where.", "required": False}
    from tests.plugins_tests.package_builder import TOKEN_SETTING, UNITS_SETTING

    _stage(
        node_client,
        upgrade_of(newer(settings=[dict(UNITS_SETTING), dict(TOKEN_SETTING), region])),
        "maintenance",
        django_capture_on_commit_callbacks,
    )

    response = superadmin_client.patch(f"{PLUGIN_URL}settings/", {"values": {"region": "eu"}}, format="json")

    assert response.status_code == 200, response.content
    assert "region" in [setting["key"] for setting in response.json()["settings"]]
    runtime = superadmin_client.get(f"{PLUGIN_URL}runtime/").json()
    assert runtime["upgrade"] == {"from_version": "0.6.0", "to_version": "0.7.0"}
    assert runtime["database"]["migrations"]["in_package"] == 2


def test_the_runtime_shows_no_upgrade_while_the_current_version_runs(weather, newer, upgrade_of, superadmin_client):
    upgrade_of(newer())

    runtime = superadmin_client.get(f"{PLUGIN_URL}runtime/").json()

    assert runtime["upgrade"] is None
    assert runtime["database"]["migrations"]["in_package"] == 1


# ---- an organization deleted during an upgrade ----


def test_an_organization_deleted_mid_upgrade_fails_its_upgrade_job_and_keeps_its_data_removal(
    backend_plugin, superadmin, django_capture_on_commit_callbacks, mocker, acme
):
    from tests.plugins_tests.conftest import mark_running
    from plugins.lifecycle.upgrade_hooks import UpgradeHookService

    mocker.patch("tables.services.organization_deletion.get_storage_backend", return_value=mocker.MagicMock(list_all_objects=lambda *a, **k: []))
    plugin = mark_running(backend_plugin(version="0.7.0", hooks={"upgrade": True, "org_removed": True}))
    cobalt = Organization.objects.create(name="Cobalt")
    grant = active_grant(plugin, cobalt, superadmin, version="0.6.0")
    PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.UPGRADING)
    grant = PluginGrant.objects.select_related("org", "plugin__current_package").get(pk=grant.pk)
    job = UpgradeHookService().ensure_job(grant)
    superadmin.is_superadmin = True
    superadmin.save(update_fields=["is_superadmin"])

    with django_capture_on_commit_callbacks(execute=True):
        OrganizationManagementService().delete_organization(superadmin, cobalt.pk, verification_phrase="delete-Cobalt")

    job.refresh_from_db()
    assert (job.state, job.error) == (HookJobState.FAILED, ORGANIZATION_DELETED)
    assert PluginHookJob.objects.filter(
        kind=HookJobKind.ORG_REMOVED, organization_id=cobalt.pk, state=HookJobState.PENDING
    ).exists()


# ---- runs ----


def test_a_run_of_an_organization_being_upgraded_says_so(weather, superadmin, acme):
    grant = active_grant(weather, acme, superadmin)
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.UPGRADING)

    with pytest.raises(PluginSuspendedError) as refused:
        PluginRunGuard().check(RunSubject(RunKind.FLOW, forecast.pk, acme.pk))

    assert str(refused.value.detail) == (
        'This run uses resources of the plugin "Weather", which is being upgraded in this organization.'
    )
    assert refused.value.default_code == "plugin_suspended"
    assert refused.value.log_key.startswith(f"weather:{grant.pk}:upgrading:")


@pytest.mark.parametrize("state", [GrantState.UPGRADING, GrantState.UPGRADE_FAILED])
def test_sessions_already_running_finish_while_their_organization_is_upgraded(
    weather, superadmin, acme, stopped_sessions, state
):
    grant = active_grant(weather, acme, superadmin)
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    Session.objects.create(graph=forecast, status=Session.SessionStatus.RUN)
    PluginGrant.objects.filter(pk=grant.pk).update(state=state)

    report = RetentionService().run()

    assert (stopped_sessions, report.sessions_stopped) == ([], 0)


def test_a_suspended_organization_s_running_sessions_are_still_stopped(weather, superadmin, acme, beta, stopped_sessions):
    upgrading = active_grant(weather, beta, superadmin)
    own(flow(beta, "Beta forecast"), upgrading)
    Session.objects.create(graph=flow(beta, "Beta forecast 2"), status=Session.SessionStatus.RUN)
    PluginGrant.objects.filter(pk=upgrading.pk).update(state=GrantState.UPGRADING)
    grant = active_grant(weather, acme, superadmin)
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    PluginSuspensionService().suspend("weather", grant.pk, superadmin)
    slipped = Session.objects.create(graph=forecast, status=Session.SessionStatus.RUN)

    report = RetentionService().run()

    assert (stopped_sessions, report.sessions_stopped) == ([slipped.pk], 1)
