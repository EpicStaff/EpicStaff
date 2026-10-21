"""`seed_plugin_node`: registers the plugin node from the environment at every start."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from plugins.models import PluginNode, PluginSigningKey
from plugins.nodes.node_authentication import node_key_hash
from rest_framework.test import APIClient

from tests.plugins_tests.conftest import GATEWAY_SECRET

pytestmark = pytest.mark.django_db

KEY = "seed-node-key-" + "k" * 40


@pytest.fixture
def node_settings(settings):
    settings.PLUGINS_ENABLED = True
    settings.PLUGINS_NODE_NAME = "node-1"
    settings.PLUGINS_NODE_KEY = KEY
    settings.PLUGINS_NODE_UID_RANGE = "20000-20999"
    return settings


def test_the_node_is_registered_with_only_the_key_s_hash(node_settings):
    call_command("seed_plugin_node")

    node = PluginNode.objects.get()
    assert node.name == "node-1"
    assert node.key_hash == node_key_hash(KEY)
    assert KEY not in node.key_hash
    assert node.internal_host == "es_plugins"
    assert (node.port_range_start, node.port_range_end) == (20001, 20999)
    assert (node.uid_range_start, node.uid_range_end) == (20000, 20999)


def test_seeding_again_updates_the_same_node(node_settings):
    call_command("seed_plugin_node")
    node_settings.PLUGINS_NODE_KEY = "rotated-" + KEY
    node_settings.PLUGINS_NODE_UID_RANGE = "30000-30099"

    call_command("seed_plugin_node")

    node = PluginNode.objects.get()
    assert node.key_hash == node_key_hash("rotated-" + KEY)
    assert (node.uid_range_start, node.uid_range_end) == (30000, 30099)


@pytest.mark.parametrize(("enabled", "key"), [(False, KEY), (True, "none"), (True, "")])
def test_nothing_is_registered_while_plugins_are_off_or_the_key_is_none(node_settings, enabled, key, capsys):
    node_settings.PLUGINS_ENABLED = enabled
    node_settings.PLUGINS_NODE_KEY = key

    call_command("seed_plugin_node")

    assert not PluginNode.objects.exists()
    assert "not registered" in capsys.readouterr().out


def test_an_invalid_uid_range_stops_the_command(node_settings):
    node_settings.PLUGINS_NODE_UID_RANGE = "100-200"

    with pytest.raises(CommandError):
        call_command("seed_plugin_node")

    assert not PluginNode.objects.exists()


def test_the_first_signing_key_is_created_at_start_up(node_settings):
    call_command("seed_plugin_node")
    call_command("seed_plugin_node")

    assert PluginSigningKey.objects.filter(retired_at__isnull=True).count() == 1


def test_a_signing_key_is_created_even_without_a_node_key(node_settings):
    node_settings.PLUGINS_NODE_KEY = "none"

    call_command("seed_plugin_node")

    assert PluginSigningKey.objects.count() == 1


def test_nothing_is_created_while_plugins_are_off(node_settings):
    node_settings.PLUGINS_ENABLED = False

    call_command("seed_plugin_node")

    assert not PluginSigningKey.objects.exists()


def test_a_renamed_node_s_old_key_stops_working(node_settings, plugins_enabled):
    call_command("seed_plugin_node")
    node_settings.PLUGINS_NODE_NAME = "node-renamed"
    node_settings.PLUGINS_NODE_KEY = "new-" + KEY

    call_command("seed_plugin_node")

    old = PluginNode.objects.get(name="node-1")
    assert old.key_hash is None
    node_settings.PLUGINS_GATEWAY_SECRET = GATEWAY_SECRET
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"PluginNodeKey {KEY}", HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET)
    assert client.get("/api/plugin-nodes/self/desired-state/").status_code == 401
    client.credentials(HTTP_AUTHORIZATION=f"PluginNodeKey new-{KEY}", HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET)
    assert client.get("/api/plugin-nodes/self/desired-state/").status_code == 200
