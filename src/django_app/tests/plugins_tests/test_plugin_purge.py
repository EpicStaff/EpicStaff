"""Deleting a plugin for good: every organization's data, the node's removal, then its rows."""

import time
from unittest import mock

import pytest
from plugins.lifecycle import plugin_purge_service
from rest_framework.test import APIClient
from plugins.lifecycle.grant_service import PluginGrantService
from plugins.lifecycle.org_removed_hooks import OrgRemovedHookService
from plugins.lifecycle.plugin_purge_service import PluginPurgeService
from plugins.models import (
    ActivityAction,
    GrantState,
    HookJobKind,
    HookJobState,
    PlacementRemovalState,
    Plugin,
    PluginActivityEvent,
    PluginDatabase,
    PluginGrant,
    PluginHookJob,
    PluginOwnedResource,
    PluginPackage,
    PluginPlacement,
    PluginState,
)

from tests.plugins_tests.conftest import mark_running, upload_file
from tests.plugins_tests.package_builder import backend_manifest, build_package
from tests.plugins_tests.suspension_helpers import orphan, secret_row

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "spa_root")]

DESIRED_STATE_URL = "/api/plugin-nodes/self/desired-state/"
REPORTS_URL = "/api/plugin-nodes/self/reports/"
HOOKS = {"install": False, "org_removed": True}


@pytest.fixture(autouse=True)
def purge_package_store(monkeypatch, package_store):
    monkeypatch.setattr(plugin_purge_service, "get_package_store", lambda: package_store)
    return package_store


@pytest.fixture
def weather(database_plugin):
    return mark_running(database_plugin(hooks=HOOKS))


@pytest.fixture
def grants(weather, superadmin, acme, beta):
    return [PluginGrantService().grant("weather", organization.pk, superadmin) for organization in (acme, beta)]


def _delete(client, phrase="purge-weather", identifier="weather"):
    return client.delete(f"/api/admin/plugins/{identifier}/", {"verification_phrase": phrase}, format="json")


def _advance(identifier="weather"):
    return PluginPurgeService().advance(Plugin.objects.get(identifier=identifier), time.monotonic() + 30)


def _settle_grants():
    """What the retention tick does for each purging grant once its two tracks are done."""
    PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED).update(state=HookJobState.SUCCEEDED)
    from plugins.lifecycle.grant_purge_service import GrantPurgeService

    for grant in PluginGrant.objects.select_related("plugin", "org"):
        GrantPurgeService().finish_if_done(grant)


def _report_removal(node_client, placement, state, generation=None, last_error=None):
    body = {
        "format": 1,
        "agent_version": "1.0.0",
        "reported_at": "2026-10-21T12:00:00Z",
        "placements": [],
        "removals": [
            {
                "placement_id": placement.pk,
                "generation": placement.restart_generation if generation is None else generation,
                "state": state,
                "last_error": last_error,
            }
        ],
    }
    response = node_client.post(REPORTS_URL, body, format="json")
    assert response.status_code == 204, response.content


# ---- the request ----


@pytest.mark.parametrize("uninstalled_first", [False, True])
def test_deleting_a_running_or_uninstalled_plugin_purges_every_grant(
    grants, superadmin_client, uninstalled_first, log_messages, django_capture_on_commit_callbacks, monkeypatch
):
    from tables.services.session_manager_service import SessionManagerService

    monkeypatch.setattr(SessionManagerService().redis_service, "publish_stop_session", lambda session_id: 1)
    if uninstalled_first:
        superadmin_client.post("/api/admin/plugins/weather/uninstall/")

    with django_capture_on_commit_callbacks(execute=True):
        response = _delete(superadmin_client)

    assert response.status_code == 202, response.content
    body = response.json()
    assert (body["state"], body["allowed_actions"]) == ("purging", [])
    assert body["purge_progress"] == {
        "grants_left": 2,
        "data_removals_waiting": 2,
        "data_removals_failed": 0,
        "node": "waiting",
        "node_error": None,
    }
    assert set(PluginGrant.objects.values_list("state", flat=True)) == {GrantState.PURGING}
    assert PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED, state=HookJobState.PENDING).count() == 2
    started = PluginActivityEvent.objects.filter(action=ActivityAction.GRANT_PURGE_STARTED)
    assert {event.detail["reason"] for event in started} == {"plugin_deleted"}
    assert PluginActivityEvent.objects.get(action=ActivityAction.PLUGIN_PURGE_STARTED).detail == {"reason": "requested"}
    plugin = Plugin.objects.get(identifier="weather")
    assert plugin.purge_started_at is not None and plugin.uninstall_requested_at is not None
    assert any(message.startswith("plugins.plugin.purge_started") for message in log_messages)


@pytest.mark.parametrize("phrase", ["purge-Weather", "purge-weather ", "", None])
def test_a_wrong_phrase_changes_nothing(grants, superadmin_client, phrase):
    response = superadmin_client.delete(
        "/api/admin/plugins/weather/", {} if phrase is None else {"verification_phrase": phrase}, format="json"
    )

    assert (response.status_code, response.json()["code"]) == (400, "invalid_purge_phrase")
    assert Plugin.objects.get(identifier="weather").state == PluginState.RUNNING
    assert not PluginGrant.objects.filter(state=GrantState.PURGING).exists()


@pytest.mark.parametrize("state", [PluginState.UPLOADED, PluginState.PURGING])
def test_a_plugin_that_cannot_be_deleted_now_says_so_before_the_phrase_is_read(weather, superadmin_client, state):
    Plugin.objects.filter(pk=weather.pk).update(state=state)

    response = _delete(superadmin_client, phrase="wrong")

    assert (response.status_code, response.json()["code"]) == (409, "plugin_not_purgeable")


def test_an_unknown_plugin_is_not_found(superadmin_client):
    assert _delete(superadmin_client, identifier="missing").json()["code"] == "plugin_not_found"
    assert superadmin_client.get("/api/admin/plugins/missing/purge-preview/").json()["code"] == "plugin_not_found"


def test_an_org_admin_cannot_delete_a_plugin(weather, client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    assert _delete(client).status_code == 403
    assert client.get("/api/admin/plugins/weather/purge-preview/").status_code == 403


# ---- the preview ----


def test_the_preview_names_what_goes(grants, superadmin_client, acme, beta, weather):
    PluginDatabase.objects.filter(plugin=weather).update(size_bytes=8_421_376)

    body = superadmin_client.get("/api/admin/plugins/weather/purge-preview/").json()

    assert body["verification_phrase"] == "purge-weather"
    assert body["plugin"] == {"identifier": "weather", "name": weather.name, "state": "running"}
    assert body["organizations"]["total"] == 2
    assert {item["organization"]["name"] for item in body["organizations"]["items"]} == {acme.name, beta.name}
    assert body["database"] == {"name": "plugin_weather", "size_bytes": 8_421_376}
    assert (body["has_backend"], body["has_spa"], body["has_org_removed_hook"], body["package_count"]) == (True, True, True, 1)
    assert body["data_removals_open"] == 0


# ---- advancing ----


def test_failed_jobs_are_skipped_by_the_platform_only_once_no_grant_is_left(grants, superadmin_client, weather, acme):
    _delete(superadmin_client)
    deleted_org_job = OrgRemovedHookService().ensure_job(
        Plugin.objects.select_related("current_package").get(pk=weather.pk),
        organization_id=999_999,
        organization_name="Gone",
        grant=None,
    )
    PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED).update(state=HookJobState.FAILED)

    _advance()
    assert not PluginHookJob.objects.filter(state=HookJobState.SKIPPED).exists()

    _settle_grants_with_failed_jobs()
    _advance()

    assert set(PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED).values_list("state", flat=True)) == {
        HookJobState.SKIPPED
    }
    skipped = PluginActivityEvent.objects.filter(action=ActivityAction.ORG_REMOVED_HOOK_SKIPPED)
    assert {event.actor_kind for event in skipped} == {"platform"}
    assert deleted_org_job.pk in {event.detail["job_id"] for event in skipped}


def _settle_grants_with_failed_jobs():
    from plugins.lifecycle.grant_purge_service import GrantPurgeService

    for grant in PluginGrant.objects.select_related("plugin", "org"):
        assert GrantPurgeService().finish_if_done(grant)


def test_removal_is_requested_only_when_no_grant_open_job_or_owned_row_is_left(
    grants, superadmin_client, weather, acme, log_messages, django_capture_on_commit_callbacks
):
    _delete(superadmin_client)
    placement = PluginPlacement.objects.get(plugin=weather)

    _advance()
    placement.refresh_from_db()
    assert placement.removal_requested_at is None  # grants left

    _settle_grants()
    leftover = secret_row(acme, "Weather old key")
    orphan(leftover, acme)
    with mock.patch.object(plugin_purge_service.OwnedResourcePurger, "purge"):
        _advance()
    placement.refresh_from_db()
    assert placement.removal_requested_at is None  # an owned row left

    PluginOwnedResource.objects.all().delete()
    job = PluginHookJob.objects.create(
        plugin=weather, organization_id=acme.pk, kind=HookJobKind.ORG_REMOVED, timeout_seconds=60, state=HookJobState.RUNNING
    )
    _advance()
    placement.refresh_from_db()
    assert placement.removal_requested_at is None  # a job running

    PluginHookJob.objects.filter(pk=job.pk).update(state=HookJobState.SUCCEEDED)
    with django_capture_on_commit_callbacks(execute=True):
        assert _advance()
    placement.refresh_from_db()
    assert placement.removal_requested_at is not None
    assert any(message.startswith("plugins.plugin.removal_requested") for message in log_messages)


def test_the_node_is_asked_to_remove_the_plugin_with_its_database(grants, superadmin_client, weather, node_client):
    _delete(superadmin_client)
    _settle_grants()
    _advance()

    state = node_client.get(DESIRED_STATE_URL).json()

    assert state["placements"] == []
    [removal] = state["removals"]
    placement = PluginPlacement.objects.get(plugin=weather)
    record = PluginDatabase.objects.get(plugin=weather)
    assert (removal["placement_id"], removal["unix_uid"], removal["port"], removal["generation"]) == (
        placement.pk,
        placement.unix_uid,
        placement.port,
        placement.restart_generation,
    )
    assert (removal["database"]["installation_id"], removal["database"]["database_name"]) == (
        record.installation_id,
        "plugin_weather",
    )
    credentials = node_client.post(f"/api/plugin-nodes/self/placements/{placement.pk}/runtime-credentials/")
    assert (credentials.status_code, credentials.json()["code"]) == (404, "placement_not_found")
    package = node_client.get(f"/api/plugin-nodes/self/packages/{weather.current_package_id}/")
    assert package.status_code == 404


# ---- the node's reports ----


@pytest.fixture
def removal_requested(grants, superadmin_client, weather):
    _delete(superadmin_client)
    _settle_grants()
    _advance()
    return PluginPlacement.objects.get(plugin=weather)


def test_removed_deletes_the_plugin_s_rows_and_after_commit_its_files(
    removal_requested, node_client, weather, purge_package_store, django_capture_on_commit_callbacks, log_messages, superadmin_client
):
    keys = list(PluginPackage.objects.filter(plugin=weather).values_list("storage_key", flat=True))
    version = PluginPackage.objects.get(plugin=weather).version
    assert all(key in purge_package_store.objects for key in keys)

    with mock.patch.object(plugin_purge_service.SpaPublisher, "remove_plugin") as remove_plugin:
        with django_capture_on_commit_callbacks(execute=True):
            _report_removal(node_client, removal_requested, "removed")

    assert not Plugin.objects.filter(identifier="weather").exists()
    assert not PluginPlacement.objects.exists()
    assert not PluginDatabase.objects.exists()
    assert not PluginHookJob.objects.exists()
    remove_plugin.assert_called_once_with("weather")
    assert not any(key in purge_package_store.objects for key in keys)
    event = PluginActivityEvent.objects.get(action=ActivityAction.PLUGIN_PURGED)
    assert event.detail == {"version": version, "had_database": True}
    assert any(message == "plugins.plugin.purged plugin=weather had_database=True" for message in log_messages)
    activity = superadmin_client.get("/api/admin/plugins/weather/activity/")
    assert activity.status_code == 200
    assert "plugin_purged" in {row["action"] for row in activity.json()["results"]}
    assert superadmin_client.get("/api/admin/plugins/weather/").json()["code"] == "plugin_not_found"


def test_a_package_file_that_cannot_be_deleted_is_logged_not_raised(
    removal_requested, node_client, purge_package_store, django_capture_on_commit_callbacks, log_messages, monkeypatch
):
    monkeypatch.setattr(purge_package_store, "delete", mock.Mock(side_effect=OSError("bucket down")))

    with mock.patch.object(plugin_purge_service.SpaPublisher, "remove_plugin"):
        with django_capture_on_commit_callbacks(execute=True):
            _report_removal(node_client, removal_requested, "removed")

    assert not Plugin.objects.filter(identifier="weather").exists()
    assert any("delete it by hand" in message for message in log_messages)


def test_removing_then_failed_records_the_error_and_the_activity_once(removal_requested, node_client, superadmin_client):
    _report_removal(node_client, removal_requested, "removing")
    removal_requested.refresh_from_db()
    assert removal_requested.removal_state == PlacementRemovalState.REMOVING

    _report_removal(node_client, removal_requested, "failed", last_error="conflict: will not delete")
    _report_removal(node_client, removal_requested, "failed", last_error="conflict: will not delete")

    removal_requested.refresh_from_db()
    assert (removal_requested.removal_state, removal_requested.removal_error) == (
        PlacementRemovalState.FAILED,
        "conflict: will not delete",
    )
    [event] = PluginActivityEvent.objects.filter(action=ActivityAction.PLUGIN_REMOVAL_FAILED)
    assert event.detail == {"error": "conflict: will not delete"}
    detail = superadmin_client.get("/api/admin/plugins/weather/").json()
    assert detail["allowed_actions"] == ["retry_removal"]
    assert (detail["purge_progress"]["node"], detail["purge_progress"]["node_error"]) == ("failed", "conflict: will not delete")
    listed = superadmin_client.get("/api/admin/plugins/").json()
    assert [row["needs_attention"] for row in listed] == [True]


def test_retry_removal_starts_a_new_generation_and_ignores_the_old_one(removal_requested, node_client, superadmin_client):
    _report_removal(node_client, removal_requested, "failed", last_error="database")
    old_generation = removal_requested.restart_generation

    response = superadmin_client.post("/api/admin/plugins/weather/retry-removal/")

    assert response.status_code == 202, response.content
    removal_requested.refresh_from_db()
    assert removal_requested.restart_generation == old_generation + 1
    assert (removal_requested.removal_state, removal_requested.removal_error) == (None, None)
    assert PluginActivityEvent.objects.filter(action=ActivityAction.PLUGIN_REMOVAL_RETRIED).count() == 1
    [removal] = node_client.get(DESIRED_STATE_URL).json()["removals"]
    assert removal["generation"] == old_generation + 1

    _report_removal(node_client, removal_requested, "removed", generation=old_generation)

    assert Plugin.objects.filter(identifier="weather").exists()


def test_retry_removal_is_refused_unless_the_node_reported_a_failure(removal_requested, superadmin_client):
    response = superadmin_client.post("/api/admin/plugins/weather/retry-removal/")

    assert (response.status_code, response.json()["code"]) == (409, "removal_not_retryable")


def test_a_report_from_another_node_is_ignored(removal_requested, other_node_client):
    _report_removal(other_node_client, removal_requested, "removed")

    assert Plugin.objects.filter(identifier="weather").exists()


def test_a_removal_report_before_removal_was_requested_is_ignored(grants, superadmin_client, weather, node_client):
    _delete(superadmin_client)

    _report_removal(node_client, PluginPlacement.objects.get(plugin=weather), "removed")

    assert Plugin.objects.filter(identifier="weather").exists()


def test_a_frontend_only_plugin_is_finalized_without_a_node(running_plugin, superadmin_client, django_capture_on_commit_callbacks):
    running_plugin()
    _delete(superadmin_client)

    with mock.patch.object(plugin_purge_service.SpaPublisher, "remove_plugin") as remove_plugin:
        with django_capture_on_commit_callbacks(execute=True):
            assert _advance()

    assert not Plugin.objects.filter(identifier="weather").exists()
    remove_plugin.assert_called_once_with("weather")
    assert PluginActivityEvent.objects.get(action=ActivityAction.PLUGIN_PURGED).detail["had_database"] is False


def test_while_the_removal_is_pending_no_new_plugin_gets_its_port_or_user_id(
    removal_requested, installation, superadmin, django_capture_on_commit_callbacks
):
    data = build_package(manifest=backend_manifest(id="almanac", name="Almanac"))
    package = installation.upload(upload_file(data), len(data), superadmin)
    with django_capture_on_commit_callbacks(execute=True):
        installation.approve(package.pk, superadmin, untrusted_acknowledged=True)

    almanac = PluginPlacement.objects.get(plugin__identifier="almanac")
    assert almanac.port != removal_requested.port
    assert almanac.unix_uid != removal_requested.unix_uid


def test_after_the_deletion_the_identifier_can_be_installed_again(
    removal_requested, node_client, installation, superadmin, django_capture_on_commit_callbacks
):
    old_installation = PluginDatabase.objects.get().installation_id
    with mock.patch.object(plugin_purge_service.SpaPublisher, "remove_plugin"):
        with django_capture_on_commit_callbacks(execute=True):
            _report_removal(node_client, removal_requested, "removed")

    data = build_package(manifest=backend_manifest(hooks=HOOKS, database={}))
    package = installation.upload(upload_file(data), len(data), superadmin)
    with django_capture_on_commit_callbacks(execute=True):
        installation.approve(package.pk, superadmin, untrusted_acknowledged=True)

    assert Plugin.objects.get(identifier="weather").state == PluginState.PROVISIONING
    assert PluginDatabase.objects.get().installation_id != old_installation


# ---- who may call the endpoints ----


def _lifecycle_endpoints(grant_id, job_id):
    base = "/api/admin/plugins/weather"
    return [
        ("post", f"{base}/uninstall/"),
        ("post", f"{base}/reinstall/"),
        ("get", f"{base}/purge-preview/"),
        ("delete", f"{base}/"),
        ("post", f"{base}/retry-removal/"),
        ("get", f"{base}/grants/{grant_id}/purge-preview/"),
        ("delete", f"{base}/grants/{grant_id}/"),
        ("get", f"{base}/org-removed-jobs/"),
        ("post", f"{base}/org-removed-jobs/{job_id}/retry/"),
        ("post", f"{base}/org-removed-jobs/{job_id}/skip/"),
    ]


def test_every_lifecycle_endpoint_refuses_an_org_admin_and_an_api_key(
    grants, weather, acme, client_as, admin_acme, issue_api_key, superadmin_user
):
    job = PluginHookJob.objects.create(
        plugin=weather, organization_id=acme.pk, kind=HookJobKind.ORG_REMOVED, timeout_seconds=60, state=HookJobState.FAILED
    )
    org_admin = client_as(admin_acme)
    org_admin.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))
    raw_key, _ = issue_api_key(user=superadmin_user)
    api_key = APIClient()
    api_key.credentials(HTTP_X_API_KEY=raw_key)
    body = {"verification_phrase": "purge-weather"}

    for client in (org_admin, api_key):
        for method, url in _lifecycle_endpoints(grants[0].pk, job.pk):
            response = getattr(client, method)(url, body, format="json")
            assert response.status_code == 403, (method, url, response.status_code)

    assert Plugin.objects.get(pk=weather.pk).state == PluginState.RUNNING
    job.refresh_from_db()
    assert job.state == HookJobState.FAILED
