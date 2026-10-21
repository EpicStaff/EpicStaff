"""What a node should run: the desired state it polls every few seconds."""

import hashlib
from collections import defaultdict

from django.utils import timezone
from epicstaff_plugin.contracts.manifest import PluginManifest
from epicstaff_plugin.json_documents import canonical_json
from src.shared.models.plugin_nodes import (
    CONTRACT_FORMAT,
    DesiredHookJob,
    DesiredPlacement,
    DesiredState,
)

from plugins.configuration.limits import plugin_limits
from plugins.configuration.setting_values import blocked_reason
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.lifecycle.hook_job_service import HookJobService
from plugins.models import PluginNode, PluginPlacement, PluginSettingValue, PluginState
from plugins.nodes.runtime_credentials_service import (
    Roster,
    RuntimeFileBuilder,
    service_account_rosters,
)

# Plugin states whose backend should be on its node. Uploaded plugins have no approved
# package yet; the later lifecycle states arrive with suspension, upgrade and uninstall.
PLACED_PLUGIN_STATES = (PluginState.PROVISIONING, PluginState.RUNNING, PluginState.FAILED)


def placements_to_run(node: PluginNode):
    """The placements of `node` whose plugin has an approved package in a placed state."""
    return (
        PluginPlacement.objects.filter(
            node=node,
            plugin__state__in=PLACED_PLUGIN_STATES,
            plugin__current_package__isnull=False,
        )
        .select_related("plugin__current_package")
        .defer("plugin__current_package__icon_bytes")
        .order_by("pk")
    )


class DesiredStateBuilder:
    """Builds a node's desired state.

    `revision` is the sha256 of the canonical JSON of the document without `revision` and
    `generated_at`, so it changes exactly when something the node acts on changes, and
    serves as the ETag. Five queries plus the signing keys, whatever the number of plugins:
    the placements, the stored setting keys, the service-account rosters and the pending
    hook jobs.
    """

    def build(self, node: PluginNode) -> DesiredState:
        placements = [
            placement
            for placement in placements_to_run(node)
            if placement.plugin.current_package.parsed_manifest.backend is not None
        ]
        plugin_ids = [placement.plugin_id for placement in placements]
        stored_keys = defaultdict(set)
        for plugin_id, key in PluginSettingValue.objects.filter(
            plugin_id__in=plugin_ids
        ).values_list("plugin_id", "key"):
            stored_keys[plugin_id].add(key)
        rosters = service_account_rosters(plugin_ids)
        hook_jobs = HookJobService().pending_jobs_by_plugin(plugin_ids)
        runtime_files = RuntimeFileBuilder(PluginSigningKeyService().jwks())
        desired = [
            self._placement(
                placement,
                stored_keys[placement.plugin_id],
                runtime_files,
                rosters[placement.plugin_id],
                hook_jobs[placement.plugin_id],
            )
            for placement in placements
        ]
        body = {
            "format": CONTRACT_FORMAT,
            "node": {"name": node.name},
            "placements": [placement.model_dump(mode="json") for placement in desired],
        }
        return DesiredState.model_validate(
            {
                **body,
                "revision": hashlib.sha256(canonical_json(body)).hexdigest(),
                "generated_at": timezone.now(),
            }
        )

    @staticmethod
    def _placement(
        placement: PluginPlacement,
        stored_keys: set[str],
        runtime_files: RuntimeFileBuilder,
        roster: Roster,
        hook_jobs: list[DesiredHookJob],
    ) -> DesiredPlacement:
        plugin = placement.plugin
        package = plugin.current_package
        manifest: PluginManifest = package.parsed_manifest
        effective = plugin_limits(plugin, manifest).effective
        blocked = blocked_reason(manifest, stored_keys) is not None
        return DesiredPlacement.model_validate(
            {
                "placement_id": placement.pk,
                "plugin_identifier": plugin.identifier,
                "desired_state": "stopped" if blocked else "running",
                "restart_generation": placement.restart_generation,
                "package": {
                    "package_id": package.pk,
                    "version": package.version,
                    "sha256": package.sha256,
                    "size": package.size,
                    "trust": package.trust,
                    # The key EpicStaff verified the signature with at approval; editing the
                    # trusted keys afterwards does not change what the node checks.
                    "signer_public_key": package.signer_public_key,
                },
                "runtime": {
                    "python": manifest.backend.python,
                    "entrypoint": manifest.backend.entrypoint,
                    "port": placement.port,
                    "unix_uid": placement.unix_uid,
                    "memory_mb": effective["memory_mb"],
                    "cpu_priority": effective["cpu_priority"],
                },
                "credentials_revision": runtime_files.credentials_revision(
                    plugin, manifest, roster
                ),
                "settings_revision": placement.settings_revision,
                "hook_jobs": hook_jobs,
            }
        )
