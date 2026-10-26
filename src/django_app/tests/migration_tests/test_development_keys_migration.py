"""plugins 0009 unapplies once development keys exist: it revokes them before `purpose` goes, so
the constraint of one current key per account comes back over node keys alone."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from plugins.identity.service_account_keys import ServiceAccountKeyService
from plugins.models import GrantState, Plugin, PluginGrant, PluginServiceAccount, PluginState
from rbac.models import Organization

BEFORE_DEVELOPMENT_MODE = [("plugins", "0008_upgrades_backups_restores")]


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _leaves():
    return MigrationExecutor(connection).loader.graph.leaf_nodes()


@pytest.mark.django_db(transaction=True)
def test_unapplying_after_a_development_runtime_file_download_keeps_only_the_node_key():
    try:
        organization = Organization.objects.create(name="migration-org")
        plugin = Plugin.objects.create(
            identifier="weather", name="Weather", description="Forecasts.", state=PluginState.RUNNING
        )
        grant = PluginGrant.objects.create(plugin=plugin, org=organization, state=GrantState.ACTIVE)
        account = PluginServiceAccount.objects.create(grant=grant)
        node_key = ServiceAccountKeyService().mint_for_plugin(plugin)[0].raw_key
        # What a download of the development runtime file mints.
        ServiceAccountKeyService().mint_development_keys(plugin)

        old_apps = _migrate(BEFORE_DEVELOPMENT_MODE)

        key_model = old_apps.get_model("plugins", "PluginServiceAccountKey")
        keys = key_model.objects.filter(service_account_id=account.pk)
        current = keys.filter(revoked_at__isnull=True, expires_at__isnull=True)
        assert list(current.values_list("prefix", flat=True)) == [node_key[:12]]
        assert keys.filter(revoked_at__isnull=False).count() == 1
    finally:
        _migrate(_leaves())
