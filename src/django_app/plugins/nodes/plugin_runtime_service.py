"""The Runtime tab: where a plugin's backend runs, what its node last saw, and restarts."""

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from epicstaff_plugin.contracts.manifest import PluginManifest

from plugins.audit import log_restart
from plugins.configuration.setting_values import blocked_reason
from plugins.exceptions import PlacementNotFoundError
from plugins.models import Plugin, PluginNode, PluginPlacement, PluginState

# A node reports every 10 s; three missed reports make it offline.
NODE_ONLINE_WINDOW = timedelta(seconds=30)


@dataclass(frozen=True)
class PluginRuntime:
    node: PluginNode | None
    node_online: bool
    placement: PluginPlacement | None
    desired_state: str
    blocked_reason: str | None


class PluginRuntimeService:
    def runtime_of(self, plugin: Plugin, manifest: PluginManifest) -> PluginRuntime:
        placement = PluginPlacement.objects.select_related("node").filter(plugin=plugin).first()
        if placement is None:
            return PluginRuntime(
                node=None,
                node_online=False,
                placement=None,
                desired_state="stopped",
                blocked_reason=None,
            )
        reason = blocked_reason(manifest, plugin.setting_values.values_list("key", flat=True))
        node = placement.node
        return PluginRuntime(
            node=node,
            node_online=node.last_seen_at is not None
            and timezone.now() - node.last_seen_at <= NODE_ONLINE_WINDOW,
            placement=placement,
            desired_state="stopped" if reason else "running",
            blocked_reason=reason,
        )

    def restart(self, plugin: Plugin, manifest: PluginManifest, actor) -> PluginRuntime:
        """Ask the node to restart the plugin's process; a `failed` plugin starts provisioning again.

        Raises:
            PlacementNotFoundError: The plugin's backend has no placement.
        """
        with transaction.atomic():
            placement = PluginPlacement.objects.select_for_update().filter(plugin=plugin).first()
            if placement is None:
                raise PlacementNotFoundError()
            placement.restart_generation = F("restart_generation") + 1
            placement.save(update_fields=["restart_generation", "updated_at"])
            Plugin.objects.filter(pk=plugin.pk, state=PluginState.FAILED).update(
                state=PluginState.PROVISIONING, updated_at=timezone.now()
            )
            placement.refresh_from_db(fields=["restart_generation"])
        log_restart(actor, plugin.identifier, placement.restart_generation)
        return self.runtime_of(plugin, manifest)
