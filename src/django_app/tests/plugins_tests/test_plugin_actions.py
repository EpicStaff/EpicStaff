"""Which lifecycle actions a plugin allows: one rule for the services, the API and the buttons."""

import pytest
from plugins.exceptions import (
    PluginNotPurgeableError,
    PluginNotUninstallableError,
    PluginNotUninstallingError,
    PluginNotUpgradableError,
    PluginUninstallingError,
    RemovalNotRetryableError,
    RestoreNotAllowedError,
    UpgradeNotCancellableError,
    UpgradeNotRetryableError,
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

# The actions of each state without an open upgrade or a newer pending package; the rows
# with an open upgrade are at the end.
EXPECTED_ACTIONS = {
    PluginState.UPLOADED: [],
    PluginState.PROVISIONING: ["uninstall", "purge"],
    PluginState.RUNNING: ["uninstall", "purge"],
    PluginState.FAILED: ["uninstall", "purge"],
    PluginState.MAINTENANCE: ["purge"],
    PluginState.UNINSTALLING: ["reinstall", "purge"],
    PluginState.PURGING: [],
}
# `upgrade` is offered only with a newer package pending, but asserting it checks the
# plugin's state only: the version rules answer for the package with their own error.
UPGRADE_STARTS_FROM = {PluginState.RUNNING, PluginState.FAILED}
REFUSALS = {
    PluginLifecycleAction.UNINSTALL: PluginNotUninstallableError,
    PluginLifecycleAction.REINSTALL: PluginNotUninstallingError,
    PluginLifecycleAction.PURGE: PluginNotPurgeableError,
    PluginLifecycleAction.RETRY_REMOVAL: RemovalNotRetryableError,
    PluginLifecycleAction.UPGRADE: PluginNotUpgradableError,
    PluginLifecycleAction.CANCEL_UPGRADE: UpgradeNotCancellableError,
    PluginLifecycleAction.RETRY_UPGRADE: UpgradeNotRetryableError,
    PluginLifecycleAction.RESTORE_BACKUP: RestoreNotAllowedError,
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

    if action in EXPECTED_ACTIONS[state] or (
        action == PluginLifecycleAction.UPGRADE and state in UPGRADE_STARTS_FROM
    ):
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


# ---- the rows with an upgrade ----

from plugins.models import PluginDatabase, PluginDatabaseRestore, PluginUpgrade  # noqa: E402

from tests.plugins_tests.upgrade_fixtures import (  # noqa: E402, F401 (fixtures)
    SECOND_MIGRATION_SQL,
    advance_url,
    backup_body,
    ledger_of,
    newer,
    upgrade_of,
    weather,
)


def _actions(plugin):
    return [action.value for action in allowed_plugin_actions(Plugin.objects.with_summary().get(pk=plugin.pk))]


def _stage(node_client, upgrade, stage, capture):
    if stage in ("maintenance", "migrating"):
        with capture(execute=True):
            node_client.post(advance_url(upgrade.pk), {"to": "maintenance"}, format="json")
    if stage == "migrating":
        node_client.post(advance_url(upgrade.pk), {"to": "migrations", "backup": backup_body(upgrade)}, format="json")
    upgrade.refresh_from_db()
    return upgrade


def _failed(upgrade):
    PluginUpgrade.objects.filter(pk=upgrade.pk).update(failed_at=upgrade.started_at)


@pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")
def test_a_newer_pending_package_offers_the_upgrade(weather, newer):
    newer()

    assert _actions(weather) == ["uninstall", "upgrade", "purge"]


@pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")
@pytest.mark.parametrize(
    ("stage", "failed", "newer_pending", "expected"),
    [
        ("preparing", False, False, ["cancel_upgrade", "purge"]),
        ("preparing", True, False, ["cancel_upgrade", "retry_upgrade", "purge"]),
        ("preparing", True, True, ["upgrade", "cancel_upgrade", "retry_upgrade", "purge"]),
        ("maintenance", False, False, ["cancel_upgrade", "purge"]),
        ("maintenance", True, True, ["upgrade", "cancel_upgrade", "retry_upgrade", "purge"]),
        ("migrating", False, False, ["purge"]),
        ("migrating", True, False, ["cancel_upgrade", "retry_upgrade", "restore_backup", "purge"]),
    ],
)
def test_the_actions_while_an_upgrade_is_open(
    weather, newer, upgrade_of, node_client, django_capture_on_commit_callbacks, stage, failed, newer_pending, expected
):
    upgrade = _stage(node_client, upgrade_of(newer("0.7.0")), stage, django_capture_on_commit_callbacks)
    if failed:
        _failed(upgrade)
    if newer_pending:
        newer("0.8.0")

    assert _actions(weather) == expected


@pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")
def test_a_failed_migration_that_changed_the_database_offers_no_cancel(
    weather, newer, upgrade_of, node_client, django_capture_on_commit_callbacks
):
    upgrade = _stage(node_client, upgrade_of(newer()), "migrating", django_capture_on_commit_callbacks)
    _failed(upgrade)
    PluginDatabase.objects.filter(plugin=weather).update(
        ledger=ledger_of(weather.current_package, ("002_conditions.sql", SECOND_MIGRATION_SQL))
    )

    assert _actions(weather) == ["retry_upgrade", "restore_backup", "purge"]


@pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")
def test_a_restore_that_runs_allows_nothing(weather, newer, upgrade_of, node_client, superadmin, django_capture_on_commit_callbacks):
    upgrade = _stage(node_client, upgrade_of(newer()), "migrating", django_capture_on_commit_callbacks)
    _failed(upgrade)
    PluginDatabaseRestore.objects.create(
        plugin_database=PluginDatabase.objects.get(plugin=weather),
        upgrade=upgrade,
        backup=upgrade.backup,
        backup_file_name=upgrade.backup.file_name,
        requested_by=superadmin,
    )

    assert _actions(weather) == []


@pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")
def test_a_plugin_that_restarted_while_preparing_keeps_the_upgrade_rows(weather, newer, upgrade_of):
    upgrade = upgrade_of(newer())
    Plugin.objects.filter(pk=weather.pk).update(state=PluginState.PROVISIONING)
    _failed(upgrade)

    assert _actions(weather) == ["cancel_upgrade", "retry_upgrade", "purge"]


@pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")
def test_the_detail_s_actions_are_the_function_s_while_an_upgrade_is_open(weather, newer, upgrade_of, superadmin_client):
    upgrade_of(newer())

    assert superadmin_client.get("/api/admin/plugins/weather/").json()["allowed_actions"] == _actions(weather)
