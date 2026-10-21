"""The runtime file of a plugin process, and the revision that tells its node to rewrite it."""

import hashlib
from collections import defaultdict

from django.conf import settings
from epicstaff_plugin.contracts.gateway_context import Jwks, PluginIdentity
from epicstaff_plugin.contracts.manifest import PluginManifest
from epicstaff_plugin.contracts.runtime import RUNTIME_FILE_FORMAT
from epicstaff_plugin.json_documents import canonical_json
from src.shared.models.plugin_nodes import RuntimeCredentials

from plugins.configuration.setting_values import runtime_settings
from plugins.exceptions import PlacementNotFoundError
from plugins.identity.service_account_keys import MintedKey, ServiceAccountKeyService
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.models import (
    Plugin,
    PluginNode,
    PluginPlacement,
    PluginServiceAccount,
    PluginSettingValue,
)
from plugins.origins import PluginOrigins

# A plugin's service accounts as the revision sees them: organization id (as text) →
# `{org_name, grant_state}`. The keys themselves never count, so minting new ones changes
# nothing the node acts on.
Roster = dict[str, dict[str, str]]


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


class RuntimeFileBuilder:
    """Builds runtime files with one JWKS, so a whole desired state agrees on the keys."""

    def __init__(self, jwks: Jwks):
        self._jwks = jwks
        self._origins = PluginOrigins()

    def credentials_revision(self, plugin: Plugin, manifest: PluginManifest, roster: Roster) -> str:
        """Hash of every runtime-file field except the settings, with the roster for the keys.

        It changes when the node must rewrite the runtime file although nothing that
        restarts the process changed: a signing-key rotation, a retired key leaving the
        JWKS, a new EpicStaff address, a grant created, entering or leaving a key-holding
        state, a granted organization renamed or deactivated. The node then fetches the
        runtime credentials again, which mints new keys. Settings have their own revision,
        which restarts.
        """
        document = {**self._without_settings(plugin, manifest), "service_accounts": roster}
        return hashlib.sha256(canonical_json(document)).hexdigest()

    def runtime_file_document(
        self,
        plugin: Plugin,
        manifest: PluginManifest,
        stored: list[PluginSettingValue],
        minted: list[MintedKey],
    ) -> dict:
        """The runtime file as plain data, secret settings decrypted and minted keys in clear.

        Not validated here: `RuntimeCredentials` validates it, so an error can never show
        a secret or a key (that model hides inputs in its errors; `RuntimeFile` alone does
        not).
        """
        plain, secret = runtime_settings(manifest, stored)
        return {
            **self._without_settings(plugin, manifest),
            "settings": plain,
            "secret_settings": secret,
            "service_accounts": {
                str(key.service_account.grant.org_id): {
                    "key": key.raw_key,
                    "org_name": key.service_account.grant.org.name,
                    "grant_state": key.service_account.grant.state,
                }
                for key in minted
            },
        }

    def _without_settings(self, plugin: Plugin, manifest: PluginManifest) -> dict:
        epicstaff_origin = self._origins.epicstaff_origin
        return {
            "format": RUNTIME_FILE_FORMAT,
            "plugin": PluginIdentity(
                identifier=plugin.identifier, version=manifest.version
            ).model_dump(),
            "issuer": epicstaff_origin,
            "public_url": self._origins.frame_origin(plugin.identifier),
            "epicstaff_public_url": epicstaff_origin,
            "epicstaff_api_url": settings.PLUGINS_INTERNAL_API_URL,
            "jwks": self._jwks.model_dump(mode="json"),
            "public_paths": [
                public_path.model_dump(mode="json") for public_path in manifest.public_paths
            ],
        }


class RuntimeCredentialsService:
    """Hands a node the runtime file of one of its placements."""

    def credentials_for(self, node: PluginNode, placement_id: int) -> RuntimeCredentials:
        """Return the runtime credentials of a placement on `node`, with freshly minted keys.

        Every call mints a new key for each of the plugin's key-holding service accounts
        (`ServiceAccountKeyService`): EpicStaff keeps only hashes, so a key cannot be handed
        over twice. The keys the previous call minted keep working for ten minutes.

        Raises:
            PlacementNotFoundError: No such placement on this node, or its plugin has no
                backend package to run.
        """
        placement = (
            PluginPlacement.objects.select_related("plugin__current_package")
            .filter(pk=placement_id, node=node, plugin__current_package__isnull=False)
            .first()
        )
        if placement is None:
            raise PlacementNotFoundError()
        plugin = placement.plugin
        manifest = plugin.current_package.parsed_manifest
        if manifest.backend is None:
            raise PlacementNotFoundError()
        builder = RuntimeFileBuilder(PluginSigningKeyService().jwks())
        minted = ServiceAccountKeyService().mint_for_plugin(plugin)
        return RuntimeCredentials.model_validate(
            {
                "placement_id": placement.pk,
                "credentials_revision": builder.credentials_revision(
                    plugin, manifest, roster_of(minted)
                ),
                "settings_revision": placement.settings_revision,
                "runtime_file": builder.runtime_file_document(
                    plugin, manifest, list(plugin.setting_values.all()), minted
                ),
            }
        )
