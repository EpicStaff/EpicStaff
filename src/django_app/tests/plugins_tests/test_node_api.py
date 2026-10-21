"""The node API: node key, desired state with its ETag, package download, reports."""

import hashlib

import pytest
from django.utils import timezone
from plugins.models import (
    PlacementObservedState,
    Plugin,
    PluginNode,
    PluginPlacement,
    PluginSettingValue,
    PluginSigningKey,
    PluginState,
)
from rest_framework.test import APIClient

from tests.plugins_tests.conftest import upload_file
from tests.plugins_tests.package_builder import TOKEN_SETTING, backend_manifest, build_package

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

DESIRED_STATE_URL = "/api/plugin-nodes/self/desired-state/"
REPORTS_URL = "/api/plugin-nodes/self/reports/"


def _package_url(package_id):
    return f"/api/plugin-nodes/self/packages/{package_id}/"


def _report(placement, **observed):
    entry = {
        "placement_id": placement.pk,
        "observed_state": "running",
        "observed_version": "0.2.0",
        "health": "ok",
        "pid": 412,
        "restarts": 0,
        "rss_mb": 61.4,
        "last_error": None,
        "log_tail": [],
        "applied_credentials_revision": None,
        "applied_settings_revision": 0,
        "applied_restart_generation": 0,
        **observed,
    }
    return {"format": 1, "agent_version": "0.1.0", "reported_at": "2026-10-21T08:00:05Z", "placements": [entry]}


# ---- authentication ----


@pytest.mark.parametrize(
    "authorization",
    [None, "PluginNodeKey wrong-key", "Bearer " + "k" * 40, "PluginNodeKey", "pluginnodekey " + "k" * 40],
    ids=["missing", "wrong key", "another scheme", "no key", "scheme in lower case"],
)
def test_a_missing_or_wrong_node_key_is_refused(plugin_node, authorization):
    client = APIClient()
    if authorization is not None:
        client.credentials(HTTP_AUTHORIZATION=authorization)

    response = client.get(DESIRED_STATE_URL)

    assert response.status_code == 401
    assert response.json()["code"] == "node_not_authenticated"


def test_the_right_node_key_is_accepted(plugin_node, node_client):
    assert node_client.get(DESIRED_STATE_URL).status_code == 200


def test_a_superadmin_s_login_does_not_open_the_node_api(plugin_node, superadmin_client):
    assert superadmin_client.get(DESIRED_STATE_URL).status_code == 401


def test_a_node_without_a_key_cannot_authenticate(plugin_node, node_client):
    PluginNode.objects.filter(pk=plugin_node.pk).update(key_hash=None)

    assert node_client.get(DESIRED_STATE_URL).status_code == 401


def test_without_a_signing_key_the_node_is_told_so(backend_plugin, plugin_node, node_client):
    backend_plugin()
    PluginSigningKey.objects.all().delete()

    response = node_client.get(DESIRED_STATE_URL)

    assert response.status_code == 503
    assert response.json()["code"] == "signing_key_missing"


# ---- desired state ----


def test_the_desired_state_describes_each_backend_on_the_node(backend_plugin, plugin_node, node_client):
    plugin = backend_plugin()
    package = plugin.current_package

    response = node_client.get(DESIRED_STATE_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["format"] == 1
    assert body["node"] == {"name": "node-1"}
    assert response["ETag"] == f'"{body["revision"]}"'
    [placement] = body["placements"]
    assert placement == {
        "placement_id": plugin.placement.pk,
        "plugin_identifier": "weather",
        "desired_state": "running",
        "restart_generation": 0,
        "package": {
            "package_id": package.pk,
            "version": "0.2.0",
            "sha256": package.sha256,
            "size": package.size,
            "trust": "untrusted",
            "signer_public_key": None,
        },
        "runtime": {
            "python": "3.12",
            "entrypoint": "plugin.app:app",
            "port": 20001,
            "unix_uid": 20000,
            "memory_mb": 256,
            "cpu_priority": "normal",
        },
        "credentials_revision": placement["credentials_revision"],
        "settings_revision": 0,
    }
    assert len(placement["credentials_revision"]) == 64


def test_a_trusted_package_names_its_signer(installation, superadmin, plugin_node, node_client, trusts_release_key, django_capture_on_commit_callbacks):
    data = build_package(manifest=backend_manifest(), signed_with=trusts_release_key)
    package = installation.upload(upload_file(data), len(data), superadmin)
    with django_capture_on_commit_callbacks(execute=True):
        installation.approve(package.pk, superadmin, untrusted_acknowledged=False)

    package_entry = node_client.get(DESIRED_STATE_URL).json()["placements"][0]["package"]

    assert package_entry["trust"] == "trusted"
    assert package_entry["signer_public_key"] == trusts_release_key.public_key.to_text()


def test_editing_the_trusted_keys_does_not_change_the_desired_state(installation, superadmin, plugin_node, node_client, trusts_release_key, settings, django_capture_on_commit_callbacks):
    data = build_package(manifest=backend_manifest(), signed_with=trusts_release_key)
    package = installation.upload(upload_file(data), len(data), superadmin)
    with django_capture_on_commit_callbacks(execute=True):
        installation.approve(package.pk, superadmin, untrusted_acknowledged=False)
    before = node_client.get(DESIRED_STATE_URL).json()

    settings.PLUGINS_TRUSTED_SIGNING_KEYS = []
    after = node_client.get(DESIRED_STATE_URL).json()

    assert after["revision"] == before["revision"]
    assert after["placements"][0]["package"]["signer_public_key"] == trusts_release_key.public_key.to_text()


def test_the_revision_is_stable_and_answers_304(backend_plugin, plugin_node, node_client):
    backend_plugin()
    first = node_client.get(DESIRED_STATE_URL)

    second = node_client.get(DESIRED_STATE_URL)
    unchanged = node_client.get(DESIRED_STATE_URL, HTTP_IF_NONE_MATCH=first["ETag"])

    assert second.json()["revision"] == first.json()["revision"]
    assert unchanged.status_code == 304
    assert unchanged["ETag"] == first["ETag"]
    assert unchanged.content == b""


def test_a_change_gives_a_new_revision(backend_plugin, plugin_node, node_client):
    plugin = backend_plugin()
    before = node_client.get(DESIRED_STATE_URL)["ETag"]
    PluginPlacement.objects.filter(plugin=plugin).update(restart_generation=1)

    response = node_client.get(DESIRED_STATE_URL, HTTP_IF_NONE_MATCH=before)

    assert response.status_code == 200
    assert response["ETag"] != before


def test_a_missing_required_setting_keeps_the_process_stopped(backend_plugin, plugin_node, node_client):
    backend_plugin(settings=[{**TOKEN_SETTING, "required": True}])

    assert node_client.get(DESIRED_STATE_URL).json()["placements"][0]["desired_state"] == "stopped"


def test_a_frontend_only_plugin_is_not_in_the_desired_state(running_plugin, plugin_node, node_client):
    running_plugin()

    assert node_client.get(DESIRED_STATE_URL).json()["placements"] == []


def test_a_node_sees_only_its_own_placements(backend_plugin, other_node, node_client, other_node_client):
    moved = backend_plugin(id="moved")
    backend_plugin(id="kept")
    PluginPlacement.objects.filter(plugin=moved).update(node=other_node, unix_uid=30000)

    mine = [placement["plugin_identifier"] for placement in node_client.get(DESIRED_STATE_URL).json()["placements"]]
    theirs = [placement["plugin_identifier"] for placement in other_node_client.get(DESIRED_STATE_URL).json()["placements"]]

    assert (mine, theirs) == (["kept"], ["moved"])


# ---- packages ----


def test_the_package_is_downloaded_with_its_digest(backend_plugin, plugin_node, node_client, package_store):
    package = backend_plugin().current_package

    response = node_client.get(_package_url(package.pk))

    assert response.status_code == 200
    body = b"".join(response.streaming_content)
    assert response["Content-Type"] == "application/octet-stream"
    assert response["Content-Length"] == str(len(body))
    assert response["X-Package-Sha256"] == package.sha256 == hashlib.sha256(body).hexdigest()
    assert body == package_store.objects[package.storage_key]


def test_another_node_s_package_is_not_found(backend_plugin, other_node, other_node_client):
    package = backend_plugin().current_package

    response = other_node_client.get(_package_url(package.pk))

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_package_not_found"


def test_a_package_that_is_not_placed_is_not_found(running_plugin, plugin_node, node_client):
    package = running_plugin().current_package

    assert node_client.get(_package_url(package.pk)).status_code == 404


# ---- reports ----


def test_a_report_updates_the_placement_and_the_node(backend_plugin, plugin_node, node_client):
    placement = backend_plugin().placement
    report = _report(placement, observed_state="failed", health="failing", pid=None, restarts=4, last_error="boom", log_tail=["line 1", "line 2"])

    response = node_client.post(REPORTS_URL, report, format="json")

    assert response.status_code == 204
    placement.refresh_from_db()
    assert (placement.observed_state, placement.health, placement.restarts) == ("failed", "failing", 4)
    assert (placement.last_error, placement.log_tail, placement.pid) == ("boom", ["line 1", "line 2"], None)
    assert placement.last_report_at is not None
    plugin_node.refresh_from_db()
    assert plugin_node.agent_version == "0.1.0"
    assert timezone.now() - plugin_node.last_seen_at < timezone.timedelta(seconds=5)


@pytest.mark.parametrize(
    ("plugin_state", "observed", "expected"),
    [
        (PluginState.PROVISIONING, {}, PluginState.RUNNING),
        (PluginState.FAILED, {}, PluginState.RUNNING),
        (PluginState.PROVISIONING, {"observed_state": "failed", "health": "failing"}, PluginState.FAILED),
        (PluginState.RUNNING, {"observed_state": "failed", "health": "failing"}, PluginState.FAILED),
        (PluginState.PROVISIONING, {"observed_version": "0.1.9"}, PluginState.PROVISIONING),
        (PluginState.PROVISIONING, {"health": "failing"}, PluginState.PROVISIONING),
        (PluginState.PROVISIONING, {"observed_state": "starting", "health": "unknown"}, PluginState.PROVISIONING),
        (PluginState.RUNNING, {"observed_state": "starting", "health": "unknown"}, PluginState.RUNNING),
        (PluginState.FAILED, {"observed_state": "downloading", "health": "unknown"}, PluginState.FAILED),
    ],
)
def test_reports_move_the_plugin_state(backend_plugin, plugin_node, node_client, plugin_state, observed, expected):
    plugin = backend_plugin()
    Plugin.objects.filter(pk=plugin.pk).update(state=plugin_state)

    node_client.post(REPORTS_URL, _report(plugin.placement, **observed), format="json")

    plugin.refresh_from_db()
    assert plugin.state == expected


@pytest.mark.parametrize(
    "applied",
    [{"applied_restart_generation": 0}, {"applied_settings_revision": 0}],
    ids=["from before the restart", "from before the settings change"],
)
def test_a_stale_report_does_not_undo_a_restart(backend_plugin, plugin_node, node_client, applied):
    plugin = backend_plugin()
    Plugin.objects.filter(pk=plugin.pk).update(state=PluginState.PROVISIONING)
    PluginPlacement.objects.filter(plugin=plugin).update(restart_generation=1, settings_revision=1)
    current = {"applied_restart_generation": 1, "applied_settings_revision": 1}
    stale = _report(plugin.placement, observed_state="failed", health="failing", **{**current, **applied})

    node_client.post(REPORTS_URL, stale, format="json")

    plugin.refresh_from_db()
    plugin.placement.refresh_from_db()
    assert plugin.state == PluginState.PROVISIONING
    assert plugin.placement.observed_state == "failed"


def test_a_stale_running_report_does_not_mark_the_plugin_running(backend_plugin, plugin_node, node_client):
    plugin = backend_plugin()
    PluginPlacement.objects.filter(plugin=plugin).update(restart_generation=2)

    node_client.post(REPORTS_URL, _report(plugin.placement, applied_restart_generation=1), format="json")

    plugin.refresh_from_db()
    assert plugin.state == PluginState.PROVISIONING


def test_a_current_report_after_a_restart_moves_the_state(backend_plugin, plugin_node, node_client):
    plugin = backend_plugin()
    PluginPlacement.objects.filter(plugin=plugin).update(restart_generation=1)

    node_client.post(REPORTS_URL, _report(plugin.placement, applied_restart_generation=1), format="json")

    plugin.refresh_from_db()
    assert plugin.state == PluginState.RUNNING


def test_a_failed_download_without_applied_values_still_fails_the_plugin(backend_plugin, plugin_node, node_client):
    plugin = backend_plugin()
    report = _report(
        plugin.placement,
        observed_state="failed",
        health="unknown",
        observed_version=None,
        applied_settings_revision=None,
        applied_restart_generation=None,
    )

    node_client.post(REPORTS_URL, report, format="json")

    plugin.refresh_from_db()
    assert plugin.state == PluginState.FAILED


def test_a_report_on_another_node_s_placement_is_ignored(backend_plugin, other_node, other_node_client):
    placement = backend_plugin().placement

    response = other_node_client.post(REPORTS_URL, _report(placement), format="json")

    assert response.status_code == 204
    placement.refresh_from_db()
    assert placement.observed_state == PlacementObservedState.UNKNOWN
    assert Plugin.objects.get(pk=placement.plugin_id).state == PluginState.PROVISIONING


def test_a_report_from_a_newer_node_with_unknown_fields_is_accepted(backend_plugin, plugin_node, node_client):
    placement = backend_plugin().placement
    report = _report(placement, cpu_percent=12.5)
    report["uptime_seconds"] = 3600

    response = node_client.post(REPORTS_URL, report, format="json")

    assert response.status_code == 204
    placement.refresh_from_db()
    assert placement.observed_state == "running"


@pytest.mark.parametrize(
    "change",
    [{"format": 2}, {"placements": [{"placement_id": 1}]}, {"reported_at": "yesterday"}, {"agent_version": ""}],
)
def test_a_malformed_report_is_refused(plugin_node, node_client, change):
    report = {"format": 1, "agent_version": "0.1.0", "reported_at": "2026-10-21T08:00:05Z", "placements": [], **change}

    response = node_client.post(REPORTS_URL, report, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_node_report"
    assert all(error["loc"].startswith("report") for error in response.json()["errors"])


def test_a_long_log_tail_is_refused(backend_plugin, plugin_node, node_client):
    placement = backend_plugin().placement

    response = node_client.post(REPORTS_URL, _report(placement, log_tail=["x"] * 201), format="json")

    assert response.status_code == 400


def test_the_runtime_settings_are_not_in_the_desired_state(backend_plugin, plugin_node, node_client):
    plugin = backend_plugin()
    PluginSettingValue.objects.create(plugin=plugin, key="units", value="imperial")

    assert b"imperial" not in node_client.get(DESIRED_STATE_URL).content
