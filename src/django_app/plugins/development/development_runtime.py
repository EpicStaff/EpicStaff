"""The development runtime file: what `epicstaff-plugin dev` runs a plugin's backend with.

It is the runtime file the plugin node gets for the plugin's placement, built by the same
`RuntimeFileBuilder`, except two fields: `service_accounts` holds development keys, for this
plugin's key-holding grants only, and `epicstaff_api_url` is the development API listener on
the host's loopback. It holds the plugin's secret settings in clear text, so it is never
stored or logged; only the number of organizations it holds keys for is recorded.
"""

from django.db import transaction
from epicstaff_plugin.contracts.runtime import RuntimeFile

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_development_runtime_file_issued
from plugins.configuration.setting_values import runtime_settings
from plugins.development.development_mode import development_api_url, development_mode_on
from plugins.exceptions import (
    PluginDevelopmentModeOffError,
    PluginHasNoBackendError,
    PluginNotRunningError,
)
from plugins.identity.service_account_keys import ServiceAccountKeyService
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.lifecycle.lifecycle_locks import lock_existing_plugin
from plugins.lifecycle.open_upgrades import node_package, open_upgrade_of
from plugins.models import PluginPlacement, PluginState
from plugins.nodes.runtime_file_builder import RuntimeFileBuilder


class DevelopmentRuntimeFileService:
    def issue(self, identifier: str, actor) -> dict:
        """Mint the plugin's development keys and return its development runtime file.

        Every earlier development key of the plugin stops working at once. All or nothing, in
        one transaction: when a secret setting cannot be decrypted or the document does not
        validate, no key is minted and none is revoked. The number of queries does not depend
        on the number of organizations the plugin is granted to.

        Raises:
            PluginNotFoundError: No such plugin.
            PluginDevelopmentModeOffError: Development mode is off.
            PluginHasNoBackendError: The package the node runs has no backend.
            PluginNotRunningError: The plugin is not running, or has no placement on a node.
        """
        with transaction.atomic():
            plugin = lock_existing_plugin(identifier)
            if not development_mode_on():
                raise PluginDevelopmentModeOffError()
            package = node_package(plugin, open_upgrade_of(plugin))
            if package is None or package.parsed_manifest.backend is None:
                raise PluginHasNoBackendError()
            if plugin.state != PluginState.RUNNING or not _placed(plugin):
                raise PluginNotRunningError()
            manifest = package.parsed_manifest
            builder = RuntimeFileBuilder(
                PluginSigningKeyService().jwks(), epicstaff_api_url=development_api_url()
            )
            # Decrypted before minting, so a secret that cannot be decrypted never mints.
            settings_and_secrets = runtime_settings(manifest, plugin.setting_values.all())
            minted = ServiceAccountKeyService().mint_development_keys(plugin)
            document = builder.runtime_file_document(plugin, manifest, settings_and_secrets, minted)
            # `RuntimeFile` hides its input in errors, so a failure never shows a key or a secret.
            RuntimeFile.model_validate(document)
            organizations = len(minted)
            ActivityRecorder().development_runtime_file_issued(
                actor, plugin.identifier, organizations
            )
            transaction.on_commit(
                lambda: log_development_runtime_file_issued(
                    actor, identifier=plugin.identifier, organizations=organizations
                )
            )
        return document


def _placed(plugin) -> bool:
    return PluginPlacement.objects.filter(plugin=plugin, removal_requested_at__isnull=True).exists()
