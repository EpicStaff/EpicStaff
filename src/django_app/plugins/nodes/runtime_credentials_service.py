"""The runtime file of a plugin process, and the revision that tells its node to rewrite it."""

import hashlib

from django.conf import settings
from epicstaff_plugin.contracts.gateway_context import Jwks, PluginIdentity
from epicstaff_plugin.contracts.manifest import PluginManifest
from epicstaff_plugin.contracts.runtime import RUNTIME_FILE_FORMAT
from epicstaff_plugin.json_documents import canonical_json
from src.shared.models.plugin_nodes import RuntimeCredentials

from plugins.configuration.setting_values import runtime_settings
from plugins.exceptions import PlacementNotFoundError
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.models import Plugin, PluginNode, PluginPlacement, PluginSettingValue
from plugins.origins import PluginOrigins


class RuntimeFileBuilder:
    """Builds runtime files with one JWKS, so a whole desired state agrees on the keys."""

    def __init__(self, jwks: Jwks):
        self._jwks = jwks
        self._origins = PluginOrigins()

    def credentials_revision(self, plugin: Plugin, manifest: PluginManifest) -> str:
        """Hash of every runtime-file field except the settings.

        It changes when the node must rewrite the runtime file although nothing that
        restarts the process changed: a signing-key rotation, a retired key leaving the
        JWKS, a new EpicStaff address. Settings have their own revision, which restarts.
        """
        document = self._without_settings(plugin, manifest)
        return hashlib.sha256(canonical_json(document)).hexdigest()

    def runtime_file_document(
        self, plugin: Plugin, manifest: PluginManifest, stored: list[PluginSettingValue]
    ) -> dict:
        """The runtime file as plain data, secret settings decrypted.

        Not validated here: `RuntimeCredentials` validates it, so an error can never show
        the secrets (that model hides inputs in its errors; `RuntimeFile` alone does not).
        """
        plain, secret = runtime_settings(manifest, stored)
        return {
            **self._without_settings(plugin, manifest),
            "settings": plain,
            "secret_settings": secret,
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
            "service_accounts": {},
            "jwks": self._jwks.model_dump(mode="json"),
            "public_paths": [
                public_path.model_dump(mode="json") for public_path in manifest.public_paths
            ],
        }


class RuntimeCredentialsService:
    """Hands a node the runtime file of one of its placements."""

    def credentials_for(self, node: PluginNode, placement_id: int) -> RuntimeCredentials:
        """Return the runtime credentials of a placement on `node`.

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
        return RuntimeCredentials.model_validate(
            {
                "placement_id": placement.pk,
                "credentials_revision": builder.credentials_revision(plugin, manifest),
                "settings_revision": placement.settings_revision,
                "runtime_file": builder.runtime_file_document(
                    plugin, manifest, list(plugin.setting_values.all())
                ),
            }
        )
