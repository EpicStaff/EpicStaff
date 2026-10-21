"""The Runtime tab: node and placement state, the online window, restarts."""

from datetime import timedelta

import pytest
from django.utils import timezone
from plugins.models import Plugin, PluginNode, PluginPlacement, PluginState

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

RUNTIME_URL = "/api/admin/plugins/weather/runtime/"
RESTART_URL = "/api/admin/plugins/weather/restart/"


def test_the_runtime_document_shows_the_node_and_the_process(backend_plugin, plugin_node, superadmin_client):
    plugin = backend_plugin()
    seen = timezone.now()
    PluginNode.objects.filter(pk=plugin_node.pk).update(last_seen_at=seen, agent_version="0.1.0")
    PluginPlacement.objects.filter(plugin=plugin).update(
        observed_state="failed",
        observed_version="0.2.0",
        health="failing",
        pid=None,
        restarts=10,
        rss_mb=12.5,
        last_error="ImportError: no module named weather",
        log_tail=["Traceback", "ImportError"],
        last_report_at=seen,
    )

    response = superadmin_client.get(RUNTIME_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["node"]["name"] == "node-1"
    assert body["node"]["online"] is True
    assert body["node"]["agent_version"] == "0.1.0"
    assert body["node"]["last_seen_at"] is not None
    placement = body["placement"]
    assert placement == {
        "port": 20001,
        "unix_uid": 20000,
        "desired_state": "running",
        "blocked_reason": None,
        "observed_state": "failed",
        "observed_version": "0.2.0",
        "health": "failing",
        "pid": None,
        "restarts": 10,
        "rss_mb": 12.5,
        "last_error": "ImportError: no module named weather",
        "log_tail": ["Traceback", "ImportError"],
        "last_report_at": placement["last_report_at"],
    }
    assert placement["last_report_at"] is not None


def test_a_new_placement_has_not_been_reported(backend_plugin, superadmin_client):
    backend_plugin()

    body = superadmin_client.get(RUNTIME_URL).json()

    assert body["node"]["online"] is False
    assert body["node"]["last_seen_at"] is None
    assert (body["placement"]["observed_state"], body["placement"]["health"]) == ("unknown", "unknown")


@pytest.mark.parametrize(("seconds_ago", "online"), [(5, True), (29, True), (31, False), (600, False)])
def test_a_node_is_online_when_it_reported_within_30_seconds(backend_plugin, plugin_node, superadmin_client, seconds_ago, online):
    backend_plugin()
    PluginNode.objects.filter(pk=plugin_node.pk).update(last_seen_at=timezone.now() - timedelta(seconds=seconds_ago))

    assert superadmin_client.get(RUNTIME_URL).json()["node"]["online"] is online


def test_a_restart_raises_the_restart_generation(backend_plugin, superadmin_client):
    plugin = backend_plugin()
    Plugin.objects.filter(pk=plugin.pk).update(state=PluginState.RUNNING)

    response = superadmin_client.post(RESTART_URL)

    assert response.status_code == 202
    assert response.json()["placement"]["port"] == 20001
    assert PluginPlacement.objects.get(plugin=plugin).restart_generation == 1
    assert Plugin.objects.get(pk=plugin.pk).state == PluginState.RUNNING


def test_restarting_a_failed_plugin_provisions_it_again(backend_plugin, superadmin_client):
    plugin = backend_plugin()
    Plugin.objects.filter(pk=plugin.pk).update(state=PluginState.FAILED)

    superadmin_client.post(RESTART_URL)

    assert Plugin.objects.get(pk=plugin.pk).state == PluginState.PROVISIONING


def test_a_restart_is_logged(backend_plugin, superadmin_client, mocker):
    backend_plugin()
    info = mocker.patch("plugins.audit.logger.info")

    superadmin_client.post(RESTART_URL)

    info.assert_called_once()
    assert info.call_args.kwargs["restart_generation"] == 1


@pytest.mark.parametrize("url", [RUNTIME_URL, RESTART_URL])
def test_a_plugin_without_a_backend_has_no_runtime(running_plugin, superadmin_client, url):
    running_plugin()

    response = superadmin_client.get(url) if url == RUNTIME_URL else superadmin_client.post(url)

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_has_no_backend"


def test_an_org_admin_cannot_restart(backend_plugin, client_as, admin_acme):
    plugin = backend_plugin()

    assert client_as(admin_acme).post(RESTART_URL).status_code == 403
    assert PluginPlacement.objects.get(plugin=plugin).restart_generation == 0
