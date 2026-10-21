"""Which lifecycle actions a plugin allows: one rule for the services, the API and the buttons."""

import pytest
from plugins.exceptions import (
    PluginNotPurgeableError,
    PluginNotUninstallableError,
    PluginNotUninstallingError,
    PluginUninstallingError,
    RemovalNotRetryableError,
)
from plugins.lifecycle import plugin_actions, plugin_purge_service, uninstall_service
from plugins.lifecycle.plugin_actions import (
    PluginLifecycleAction,
    allowed_plugin_actions,
    assert_plugin_action,
    assert_plugin_in_service,
    assert_plugin_not_purging,
)
from plugins.lifecycle.plugin_purge_service import PluginPurgeService
from plugins.lifecycle.uninstall_service import PluginUninstallService
from plugins.models import PlacementRemovalState, Plugin, PluginPlacement, PluginState
from plugins.serializers.admin import PluginDetailSerializer

pytestmark = [pytest.mark.django_db]

EXPECTED_ACTIONS = {
    PluginState.UPLOADED: [],
    PluginState.PROVISIONING: ["uninstall", "purge"],
    PluginState.RUNNING: ["uninstall", "purge"],
    PluginState.FAILED: ["uninstall", "purge"],
    PluginState.MAINTENANCE: [],
    PluginState.UNINSTALLING: ["reinstall", "purge"],
    PluginState.PURGING: [],
}
REFUSALS = {
    PluginLifecycleAction.UNINSTALL: PluginNotUninstallableError,
    PluginLifecycleAction.REINSTALL: PluginNotUninstallingError,
    PluginLifecycleAction.PURGE: PluginNotPurgeableError,
    PluginLifecycleAction.RETRY_REMOVAL: RemovalNotRetryableError,
}


@pytest.fixture
def plugin(backend_plugin):
    return backend_plugin()


def _set(plugin, state, removal_state=None):
    Plugin.objects.filter(pk=plugin.pk).update(state=state)
    PluginPlacement.objects.filter(plugin=plugin).update(removal_state=removal_state)
    return Plugin.objects.with_summary().get(pk=plugin.pk)


def test_every_plugin_state_is_in_the_table():
    assert set(EXPECTED_ACTIONS) == set(PluginState)


@pytest.mark.parametrize("state", list(PluginState))
def test_the_allowed_actions_of_each_state(plugin, state):
    assert allowed_plugin_actions(_set(plugin, state)) == EXPECTED_ACTIONS[state]


def test_a_purging_plugin_whose_removal_failed_allows_a_retry_only(plugin):
    assert allowed_plugin_actions(_set(plugin, PluginState.PURGING, PlacementRemovalState.FAILED)) == ["retry_removal"]
    assert allowed_plugin_actions(_set(plugin, PluginState.PURGING, PlacementRemovalState.REMOVING)) == []


def test_a_frontend_only_plugin_never_has_a_removal_to_retry(running_plugin):
    plugin = running_plugin()
    Plugin.objects.filter(pk=plugin.pk).update(state=PluginState.PURGING)

    assert allowed_plugin_actions(Plugin.objects.with_summary().get(pk=plugin.pk)) == []


@pytest.mark.parametrize("state", list(PluginState))
@pytest.mark.parametrize("action", list(PluginLifecycleAction))
def test_an_action_outside_the_state_s_list_raises_its_own_conflict(plugin, state, action):
    loaded = _set(plugin, state)

    if action in EXPECTED_ACTIONS[state]:
        assert_plugin_action(loaded, action)
    else:
        with pytest.raises(REFUSALS[action]):
            assert_plugin_action(loaded, action)


@pytest.mark.parametrize("state", list(PluginState))
def test_the_serializer_s_allowed_actions_are_the_function_s(plugin, state):
    loaded = _set(plugin, state)

    assert PluginDetailSerializer(loaded).data["allowed_actions"] == [
        action.value for action in allowed_plugin_actions(loaded)
    ]


@pytest.mark.parametrize(
    ("state", "in_service", "editable"),
    [
        (PluginState.RUNNING, True, True),
        (PluginState.FAILED, True, True),
        (PluginState.UNINSTALLING, False, True),
        (PluginState.PURGING, False, False),
    ],
)
def test_what_an_uninstalled_or_deleting_plugin_still_allows(plugin, state, in_service, editable):
    loaded = _set(plugin, state)

    for check, allowed in ((assert_plugin_in_service, in_service), (assert_plugin_not_purging, editable)):
        if allowed:
            check(loaded)
        else:
            with pytest.raises(PluginUninstallingError):
                check(loaded)


@pytest.fixture
def asked(monkeypatch):
    """The (plugin state, action) pairs the services ask `assert_plugin_action` about."""
    calls = []
    real = plugin_actions.assert_plugin_action

    def recording(plugin, action):
        calls.append((plugin.state, action))
        real(plugin, action)

    monkeypatch.setattr(uninstall_service, "assert_plugin_action", recording)
    monkeypatch.setattr(plugin_purge_service, "assert_plugin_action", recording)
    return calls


def test_each_service_asks_the_rule_before_it_acts(plugin, superadmin, asked):
    mark = Plugin.objects.filter(pk=plugin.pk)
    mark.update(state=PluginState.RUNNING)

    PluginUninstallService().uninstall("weather", superadmin)
    PluginUninstallService().reinstall("weather", superadmin)
    mark.update(state=PluginState.RUNNING)
    PluginPurgeService().request("weather", {"verification_phrase": "purge-weather"}, superadmin)
    PluginPlacement.objects.filter(plugin=plugin).update(removal_state=PlacementRemovalState.FAILED)
    PluginPurgeService().retry_removal("weather", superadmin)

    assert asked == [
        (PluginState.RUNNING, PluginLifecycleAction.UNINSTALL),
        (PluginState.UNINSTALLING, PluginLifecycleAction.REINSTALL),
        (PluginState.RUNNING, PluginLifecycleAction.PURGE),
        (PluginState.PURGING, PluginLifecycleAction.RETRY_REMOVAL),
    ]
