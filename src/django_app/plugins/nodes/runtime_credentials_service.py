"""The runtime credentials of a plugin process on its node, and the roster its revision counts."""

from collections import defaultdict

from django.db import transaction
from src.shared.models.plugin_nodes import RuntimeCredentials

from plugins.configuration.setting_values import runtime_settings
from plugins.databases.database_records import app_password_of
from plugins.exceptions import PlacementNotFoundError
from plugins.identity.service_account_keys import MintedKey, ServiceAccountKeyService
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.lifecycle.open_upgrades import node_package, open_upgrade_of
from plugins.models import (
    PluginNode,
    PluginPlacement,
    PluginServiceAccount,
)
from plugins.nodes.runtime_file_builder import Roster, RuntimeFileBuilder


def service_account_rosters(plugin_ids: list[int]) -> dict[int, Roster]:
    """The roster of each plugin's key-holding service accounts, in one query."""
    rosters: dict[int, Roster] = defaultdict(dict)
    if not plugin_ids:
        return rosters
    rows = (
        PluginServiceAccount.objects.key_holding()
        .filter(grant__plugin_id__in=plugin_ids)
        .values_list("grant__plugin_id", "grant__org_id", "grant__org__name", "grant__state")
    )
    for plugin_id, org_id, org_name, grant_state in rows:
        rosters[plugin_id][str(org_id)] = {"org_name": org_name, "grant_state": grant_state}
    return rosters


def roster_of(minted: list[MintedKey]) -> Roster:
    return {
        str(key.service_account.grant.org_id): {
            "org_name": key.service_account.grant.org.name,
            "grant_state": key.service_account.grant.state,
        }
        for key in minted
    }


class RuntimeCredentialsService:
    """Hands a node the runtime file of one of its placements."""

    def credentials_for(self, node: PluginNode, placement_id: int) -> RuntimeCredentials:
        """Return the runtime credentials of a placement on `node`, with freshly minted keys.

        The runtime file is the node package's (`node_package`): the upgrade's target once the
        plugin is stopped for it, with that version's settings, public paths and version. For
        a node package with a database they also carry its app role's password, decrypted. It
        never goes into the runtime file, and only this node gets it.

        Every call mints a new key for each of the plugin's key-holding service accounts
        (`ServiceAccountKeyService`): EpicStaff keeps only hashes, so a key cannot be handed
        over twice. The keys the previous call minted keep working for ten minutes.

        All or nothing, in one transaction: when the secret settings or the app password
        cannot be decrypted or the document does not validate, no key is minted and none is
        superseded or revoked, so the process keeps running on the keys it has.

        Raises:
            PlacementNotFoundError: No such placement on this node, its plugin has no
                backend package to run, or the plugin is being removed from the node.
        """
        with transaction.atomic():
            placement = (
                PluginPlacement.objects.select_related(
                    "plugin__current_package", "plugin__database"
                )
                .defer("plugin__current_package__icon_bytes")
                .filter(
                    pk=placement_id,
                    node=node,
                    plugin__current_package__isnull=False,
                    removal_requested_at__isnull=True,
                )
                .first()
            )
            if placement is None:
                raise PlacementNotFoundError()
            plugin = placement.plugin
            manifest = node_package(plugin, open_upgrade_of(plugin)).parsed_manifest
            if manifest.backend is None:
                raise PlacementNotFoundError()
            builder = RuntimeFileBuilder(PluginSigningKeyService().jwks())
            # Decrypted before minting, so a secret that cannot be decrypted never mints.
            settings_and_secrets = runtime_settings(manifest, plugin.setting_values.all())
            database = (
                {"app_password": app_password_of(plugin.database)}
                if manifest.database is not None
                else None
            )
            minted = ServiceAccountKeyService().mint_for_plugin(plugin)
            return RuntimeCredentials.model_validate(
                {
                    "placement_id": placement.pk,
                    "credentials_revision": builder.credentials_revision(
                        plugin, manifest, roster_of(minted)
                    ),
                    "settings_revision": placement.settings_revision,
                    "runtime_file": builder.runtime_file_document(
                        plugin, manifest, settings_and_secrets, minted
                    ),
                    "database": database,
                }
            )
