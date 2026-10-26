"""The one builder of a plugin process's runtime file (`RuntimeFile`, runtime file version 1).

The node's runtime credentials and the development runtime file are both built here, so the
two documents differ only where they must: the keys and the API address.
"""

import hashlib

from django.conf import settings
from epicstaff_plugin.contracts.gateway_context import Jwks, PluginIdentity
from epicstaff_plugin.contracts.manifest import PluginManifest
from epicstaff_plugin.contracts.runtime import RUNTIME_FILE_FORMAT
from epicstaff_plugin.json_documents import canonical_json

from plugins.identity.service_account_keys import MintedKey
from plugins.models import Plugin
from plugins.origins import PluginOrigins

# A plugin's service accounts as the revision sees them: organization id (as text) →
# `{org_name, grant_state}`. The keys themselves never count, so minting new ones changes
# nothing the node acts on.
Roster = dict[str, dict[str, str]]


class RuntimeFileBuilder:
    """Builds runtime files with one JWKS, so a whole desired state agrees on the keys.

    `epicstaff_api_url` is where the process reaches EpicStaff's API: the internal listener on
    the plugins network for the node's processes (`PLUGINS_INTERNAL_API_URL`), the development
    API listener for a development backend.
    """

    def __init__(self, jwks: Jwks, *, epicstaff_api_url: str | None = None):
        self._jwks = jwks
        self._origins = PluginOrigins()
        self._epicstaff_api_url = epicstaff_api_url or settings.PLUGINS_INTERNAL_API_URL

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
        settings_and_secrets: tuple[dict, dict],
        minted: list[MintedKey],
    ) -> dict:
        """The runtime file as plain data, secret settings decrypted and minted keys in clear.

        `settings_and_secrets` is what `runtime_settings` returns. Not validated here: the
        caller validates it (`RuntimeCredentials`, or the SDK's `RuntimeFile`), and both hide
        their inputs in errors, so an error never shows a secret or a key.
        """
        plain, secret = settings_and_secrets
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
            "epicstaff_api_url": self._epicstaff_api_url,
            "jwks": self._jwks.model_dump(mode="json"),
            "public_paths": [
                public_path.model_dump(mode="json") for public_path in manifest.public_paths
            ],
        }
