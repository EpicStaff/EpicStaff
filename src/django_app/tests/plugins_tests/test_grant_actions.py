"""Which lifecycle actions a grant allows: one rule for the services, the API and the buttons."""

import pytest
from plugins.exceptions import GrantNotSuspendableError, GrantNotSuspendedError, HookNotRetryableError
from plugins.lifecycle import grant_actions, hook_job_service, suspension_service
from plugins.lifecycle.grant_actions import GrantAction, allowed_grant_actions, assert_grant_action
from plugins.lifecycle.hook_job_service import HookJobService
from plugins.lifecycle.suspension_service import PluginSuspensionService
from plugins.models import GrantState, PluginGrant
from plugins.serializers.admin import PluginGrantSerializer

from tests.plugins_tests.suspension_helpers import set_state

pytestmark = [pytest.mark.django_db]

EXPECTED_ACTIONS = {
    GrantState.GRANTING: ["suspend"],
    GrantState.ACTIVE: ["suspend"],
    GrantState.INSTALL_FAILED: ["retry_install", "suspend"],
    GrantState.SUSPENDED: ["resume"],
    GrantState.UPGRADING: [],
    GrantState.UPGRADE_FAILED: [],
    GrantState.PURGING: [],
}
REFUSALS = {
    GrantAction.SUSPEND: GrantNotSuspendableError,
    GrantAction.RESUME: GrantNotSuspendedError,
    GrantAction.RETRY_INSTALL: HookNotRetryableError,
}


@pytest.fixture
def grant(running_plugin, grant_to, acme):
    return grant_to(running_plugin(), acme)


def test_every_grant_state_is_in_the_table():
    assert set(EXPECTED_ACTIONS) == set(GrantState)


@pytest.mark.parametrize("state", list(GrantState))
def test_the_allowed_actions_of_each_state(grant, state):
    grant.state = state

    assert allowed_grant_actions(grant) == EXPECTED_ACTIONS[state]


@pytest.mark.parametrize("state", list(GrantState))
@pytest.mark.parametrize("action", list(GrantAction))
def test_an_action_outside_the_state_s_list_raises_its_own_conflict(grant, state, action):
    grant.state = state

    if action in EXPECTED_ACTIONS[state]:
        assert_grant_action(grant, action)
    else:
        with pytest.raises(REFUSALS[action]):
            assert_grant_action(grant, action)


@pytest.mark.parametrize("state", list(GrantState))
def test_the_serializer_s_allowed_actions_are_the_function_s(grant, state):
    set_state(grant, state)
    row = PluginGrant.objects.with_admin_details().get(pk=grant.pk)

    assert PluginGrantSerializer(row).data["allowed_actions"] == [action.value for action in allowed_grant_actions(row)]


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
    return calls


def test_suspend_and_resume_ask_the_rule(grant, superadmin, asked):
    PluginSuspensionService().suspend("weather", grant.pk, superadmin)
    PluginSuspensionService().resume("weather", grant.pk, superadmin)

    assert asked == [(GrantState.ACTIVE, GrantAction.SUSPEND), (GrantState.SUSPENDED, GrantAction.RESUME)]


def test_retrying_the_install_hook_asks_the_rule(grant, superadmin, asked):
    with pytest.raises(HookNotRetryableError):
        HookJobService().retry("weather", grant.pk, superadmin)

    assert asked == [(GrantState.ACTIVE, GrantAction.RETRY_INSTALL)]
