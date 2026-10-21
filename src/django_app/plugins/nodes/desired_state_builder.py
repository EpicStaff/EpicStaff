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
    DesiredRemoval,
    DesiredState,
)

from plugins.configuration.limits import plugin_limits
from plugins.configuration.setting_values import blocked_reason
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.lifecycle.hook_job_service import HookJobService
from plugins.models import (
    HookJobKind,
    HookJobState,
    Plugin,
    PluginHookJob,
    PluginNode,
    PluginPlacement,
    PluginSettingValue,
    PluginState,
)
from plugins.nodes.runtime_credentials_service import (
    Roster,
    RuntimeFileBuilder,
    service_account_rosters,
)

# Plugin states whose backend is in service: the gateway forwards to it and a grant may be
# made. Uploaded plugins have no approved package yet.
PLACED_PLUGIN_STATES = (PluginState.PROVISIONING, PluginState.RUNNING, PluginState.FAILED)
# Plugin states whose backend the node keeps: in service, uninstalled or being deleted. An
# uninstalled or deleting plugin's process is stopped except while an organization removed
# hook is due or running. Not the gateway's set: the gateway serves none of these two.
NODE_PLUGIN_STATES = (*PLACED_PLUGIN_STATES, PluginState.UNINSTALLING, PluginState.PURGING)
_OUT_OF_SERVICE = (PluginState.UNINSTALLING, PluginState.PURGING)
# Columns of a plugin's database record the desired state never reads.
_UNREAD_DATABASE_FIELDS = (
    "plugin__database__app_password_encrypted",
    "plugin__database__applied_migrations",
    "plugin__database__last_error",
)


def placements_to_run(node: PluginNode):
    """The placements of `node` its node should keep: their plugin has an approved package in
    a node state, and its removal has not been requested."""
    return (
        PluginPlacement.objects.filter(
            node=node,
            plugin__state__in=NODE_PLUGIN_STATES,
            plugin__current_package__isnull=False,
            removal_requested_at__isnull=True,
        )
        .select_related("plugin__current_package", "plugin__database__server")
        .defer("plugin__current_package__icon_bytes", *_UNREAD_DATABASE_FIELDS)
        .order_by("pk")
    )


def placements_to_remove(node: PluginNode):
    """The placements of `node` whose plugin is being deleted and whose removal was requested."""
    return (
        PluginPlacement.objects.filter(
            node=node, plugin__state=PluginState.PURGING, removal_requested_at__isnull=False
        )
        .select_related("plugin__current_package", "plugin__database__server")
        .defer("plugin__current_package__icon_bytes", *_UNREAD_DATABASE_FIELDS)
        .order_by("pk")
    )


class DesiredStateBuilder:
    """Builds a node's desired state.

    `revision` is the sha256 of the canonical JSON of the document without `revision` and
    `generated_at`, so it changes exactly when something the node acts on changes, and
    serves as the ETag; an organization removed job changes it when it becomes due. Six
    queries plus the signing keys, whatever the number of plugins: the placements (with each
    plugin's database record and its server), the stored setting keys, the service-account
    rosters, the pending hook jobs and the placements to remove; one more for the running
    organization removed jobs when a plugin is uninstalled or being deleted.
    """

    def build(self, node: PluginNode) -> DesiredState:
        now = timezone.now()
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
        hook_jobs = HookJobService().pending_jobs_by_plugin(plugin_ids, now)
        hook_running = _running_org_removed(
            [
                placement.plugin_id
                for placement in placements
                if placement.plugin.state in _OUT_OF_SERVICE
            ]
        )
        runtime_files = RuntimeFileBuilder(PluginSigningKeyService().jwks())
        desired = [
            self._placement(
                placement,
                stored_keys[placement.plugin_id],
                runtime_files,
                rosters[placement.plugin_id],
                hook_jobs[placement.plugin_id],
                hook_running=placement.plugin_id in hook_running,
            )
            for placement in placements
        ]
        removals = [_removal(placement) for placement in placements_to_remove(node)]
        body = {
            "format": CONTRACT_FORMAT,
            "node": {"name": node.name},
            "placements": [placement.model_dump(mode="json") for placement in desired],
            "removals": [removal.model_dump(mode="json") for removal in removals],
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
        *,
        hook_running: bool,
    ) -> DesiredPlacement:
        plugin = placement.plugin
        package = plugin.current_package
        manifest: PluginManifest = package.parsed_manifest
        effective = plugin_limits(plugin, manifest).effective
        blocked = blocked_reason(manifest, stored_keys) is not None
        # Out of service, the process runs only to make an organization removed call: one
        # that is due (listed) or still running.
        idle = plugin.state in _OUT_OF_SERVICE and not (
            hook_running or any(job.kind == HookJobKind.ORG_REMOVED for job in hook_jobs)
        )
        return DesiredPlacement.model_validate(
            {
                "placement_id": placement.pk,
                "plugin_identifier": plugin.identifier,
                "desired_state": "stopped" if blocked or idle else "running",
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
                "database": _database_section(plugin, manifest, effective),
                "egress": {"hosts": [outbound.host for outbound in manifest.outbound_hosts]},
            }
        )


def _running_org_removed(plugin_ids: list[int]) -> set[int]:
    """The plugins among `plugin_ids` with an organization removed job running; no query for none."""
    if not plugin_ids:
        return set()
    return set(
        PluginHookJob.objects.filter(
            plugin_id__in=plugin_ids, kind=HookJobKind.ORG_REMOVED, state=HookJobState.RUNNING
        ).values_list("plugin_id", flat=True)
    )


def _removal(placement: PluginPlacement) -> DesiredRemoval:
    """What the node removes for a deleted plugin: its process, user id and port, and the
    database its record names, whatever state the record is in."""
    plugin = placement.plugin
    record = getattr(plugin, "database", None)
    database = None
    if record is not None:
        manifest = plugin.current_package.parsed_manifest
        database = _database_fields(record, plugin_limits(plugin, manifest).effective)
    return DesiredRemoval.model_validate(
        {
            "placement_id": placement.pk,
            "plugin_identifier": plugin.identifier,
            "unix_uid": placement.unix_uid,
            "port": placement.port,
            "generation": placement.restart_generation,
            "database": database,
        }
    )


def _database_section(plugin: Plugin, manifest: PluginManifest, effective: dict) -> dict | None:
    """The plugin's database as its node provisions it, with the effective limits; None
    when the current package has no database.

    Approval creates the record of every package with a database, so the record is there.
    """
    if manifest.database is None:
        return None
    return _database_fields(plugin.database, effective)


def _database_fields(record, effective: dict) -> dict:
    server = record.server
    return {
        "server": {"name": server.name, "host": server.host, "port": server.port},
        "installation_id": record.installation_id,
        "database_name": record.database_name,
        "owner_role": record.owner_role,
        "app_role": record.app_role,
        "job_role": record.job_role,
        "connection_limit": effective["db_connections"],
        "statement_timeout_seconds": effective["statement_timeout_seconds"],
    }
