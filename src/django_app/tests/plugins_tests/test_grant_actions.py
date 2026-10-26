"""Which lifecycle actions a grant allows: one rule for the services, the API and the buttons.

A grant's actions depend on its state and on its plugin's.
"""

import pytest
from plugins.exceptions import (
    GrantNotPurgeableError,
    GrantNotSuspendableError,
    GrantNotSuspendedError,
    HookNotRetryableError,
    PluginUninstallingError,
)
from plugins.lifecycle import grant_actions, grant_purge_service, hook_job_service, suspension_service
from plugins.lifecycle.grant_actions import GrantAction, allowed_grant_actions, assert_grant_action
from plugins.lifecycle.grant_purge_service import GrantPurgeService
from plugins.lifecycle.hook_job_service import HookJobService
from plugins.lifecycle.suspension_service import PluginSuspensionService
from plugins.models import GrantState, Plugin, PluginGrant, PluginState
from plugins.ownership.owned_resource_summary import with_owned_resource_counts
from plugins.serializers.admin import PluginGrantSerializer

from tests.plugins_tests.suspension_helpers import set_state

pytestmark = [pytest.mark.django_db]

# The grant's actions while its plugin is in service (provisioning, running, failed, or in
# maintenance).
IN_SERVICE_ACTIONS = {
    GrantState.GRANTING: ["suspend", "purge"],
    GrantState.ACTIVE: ["suspend", "purge"],
    GrantState.INSTALL_FAILED: ["retry_install", "suspend", "purge"],
    GrantState.SUSPENDED: ["resume", "purge"],
    GrantState.UPGRADING: ["suspend", "purge"],
    GrantState.UPGRADE_FAILED: ["retry_upgrade", "suspend", "purge"],
    GrantState.PURGING: [],
}
UNINSTALLED_ACTIONS = {
    state: ["purge"] if "purge" in actions else [] for state, actions in IN_SERVICE_ACTIONS.items()
}
PURGING_ACTIONS = {state: [] for state in IN_SERVICE_ACTIONS}
EXPECTED_ACTIONS = {
    PluginState.PROVISIONING: IN_SERVICE_ACTIONS,
    PluginState.RUNNING: IN_SERVICE_ACTIONS,
    PluginState.FAILED: IN_SERVICE_ACTIONS,
    PluginState.MAINTENANCE: IN_SERVICE_ACTIONS,
    PluginState.UNINSTALLING: UNINSTALLED_ACTIONS,
    PluginState.PURGING: PURGING_ACTIONS,
}
REFUSALS = {
    GrantAction.SUSPEND: GrantNotSuspendableError,
    GrantAction.RESUME: GrantNotSuspendedError,
    GrantAction.RETRY_INSTALL: HookNotRetryableError,
    GrantAction.RETRY_UPGRADE: HookNotRetryableError,
    GrantAction.PURGE: GrantNotPurgeableError,
}
PLUGIN_STATES_WITH_GRANTS = list(EXPECTED_ACTIONS)


@pytest.fixture
def grant(running_plugin, grant_to, acme):
    return grant_to(running_plugin(), acme)


def test_every_grant_state_is_in_the_table():
    assert set(IN_SERVICE_ACTIONS) == set(GrantState)
    assert set(EXPECTED_ACTIONS) == set(PluginState) - {PluginState.UPLOADED}


@pytest.mark.parametrize("plugin_state", PLUGIN_STATES_WITH_GRANTS)
@pytest.mark.parametrize("state", list(GrantState))
def test_the_allowed_actions_of_each_state(grant, state, plugin_state):
    grant.state = state
    grant.plugin.state = plugin_state

    assert allowed_grant_actions(grant) == EXPECTED_ACTIONS[plugin_state][state]


@pytest.mark.parametrize("plugin_state", PLUGIN_STATES_WITH_GRANTS)
@pytest.mark.parametrize("state", list(GrantState))
@pytest.mark.parametrize("action", list(GrantAction))
def test_an_action_outside_the_state_s_list_raises_its_own_conflict(grant, state, plugin_state, action):
    grant.state = state
    grant.plugin.state = plugin_state

    if action in EXPECTED_ACTIONS[plugin_state][state]:
        assert_grant_action(grant, action)
    else:
        with pytest.raises((REFUSALS[action], PluginUninstallingError)):
            assert_grant_action(grant, action)


@pytest.mark.parametrize("action", [GrantAction.SUSPEND, GrantAction.RESUME, GrantAction.RETRY_INSTALL])
@pytest.mark.parametrize("plugin_state", [PluginState.UNINSTALLING, PluginState.PURGING])
def test_a_grant_change_the_plugin_s_state_refuses_says_so(grant, action, plugin_state):
    grant.state = {
        GrantAction.SUSPEND: GrantState.ACTIVE,
        GrantAction.RESUME: GrantState.SUSPENDED,
        GrantAction.RETRY_INSTALL: GrantState.INSTALL_FAILED,
    }[action]
    grant.plugin.state = plugin_state

    with pytest.raises(PluginUninstallingError):
        assert_grant_action(grant, action)


def test_a_grant_of_a_plugin_being_deleted_cannot_be_purged_again(grant):
    grant.plugin.state = PluginState.PURGING

    with pytest.raises(GrantNotPurgeableError):
        assert_grant_action(grant, GrantAction.PURGE)


@pytest.mark.parametrize("plugin_state", PLUGIN_STATES_WITH_GRANTS)
@pytest.mark.parametrize("state", list(GrantState))
def test_the_serializer_s_allowed_actions_are_the_function_s(grant, state, plugin_state):
    set_state(grant, state)
    Plugin.objects.filter(pk=grant.plugin_id).update(state=plugin_state)
    [row] = with_owned_resource_counts([PluginGrant.objects.with_admin_details().get(pk=grant.pk)])

    assert PluginGrantSerializer(row).data["allowed_actions"] == [action.value for action in allowed_grant_actions(row)]
    assert PluginGrantSerializer(row).data["allowed_actions"] == EXPECTED_ACTIONS[plugin_state][state]


@pytest.fixture
def asked(monkeypatch):
    """The (grant state, action) pairs the services ask `assert_grant_action` about."""
    calls = []
    real = grant_actions.assert_grant_action

    def recording(grant, action):
        calls.append((grant.state, action))
        real(grant, action)

    monkeypatch.setattr(suspension_service, "assert_grant_action", recording)
    monkeypatch.setattr(hook_job_service, "assert_grant_action", recording)
    monkeypatch.setattr(grant_purge_service, "assert_grant_action", recording)
    return calls


def test_suspend_and_resume_ask_the_rule(grant, superadmin, asked):
    PluginSuspensionService().suspend("weather", grant.pk, superadmin)
    PluginSuspensionService().resume("weather", grant.pk, superadmin)

    assert asked == [(GrantState.ACTIVE, GrantAction.SUSPEND), (GrantState.SUSPENDED, GrantAction.RESUME)]


def test_retrying_the_install_hook_asks_the_rule(grant, superadmin, asked):
    with pytest.raises(HookNotRetryableError):
        HookJobService().retry("weather", grant.pk, superadmin)

    assert asked == [(GrantState.ACTIVE, GrantAction.RETRY_INSTALL)]


def test_deleting_a_grant_s_data_asks_the_rule(grant, superadmin, asked):
    GrantPurgeService().request("weather", grant.pk, {"verification_phrase": f"purge-weather-{grant.org.name}"}, superadmin)

    assert asked == [(GrantState.ACTIVE, GrantAction.PURGE)]
