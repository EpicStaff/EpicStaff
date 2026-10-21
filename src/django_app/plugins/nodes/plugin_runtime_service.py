"""The Runtime tab: where a plugin's backend runs, what its node last saw, its database, its
outbound hosts, and restarts."""

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from epicstaff_plugin.contracts.manifest import OutboundHost, PluginManifest

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_restart
from plugins.configuration.limits import plugin_limits
from plugins.configuration.setting_values import blocked_reason
from plugins.exceptions import PlacementNotFoundError, PluginNotFoundError
from plugins.lifecycle.lifecycle_locks import lock_plugin
from plugins.lifecycle.plugin_actions import assert_plugin_in_service
from plugins.models import Plugin, PluginDatabase, PluginNode, PluginPlacement, PluginState

# A node reports every 10 s; three missed reports make it offline.
NODE_ONLINE_WINDOW = timedelta(seconds=30)


@dataclass(frozen=True)
class RuntimeDatabase:
    """A plugin's database record, with the limits its app role gets now."""

    record: PluginDatabase
    connection_limit: int
    statement_timeout_seconds: int
    migrations_in_package: int


@dataclass(frozen=True)
class PluginRuntime:
    node: PluginNode | None
    node_online: bool
    placement: PluginPlacement | None
    desired_state: str
    blocked_reason: str | None
    database: RuntimeDatabase | None
    outbound_hosts: list[OutboundHost]


class PluginRuntimeService:
    def runtime_of(self, plugin: Plugin, manifest: PluginManifest) -> PluginRuntime:
        """What the Runtime tab shows of `plugin`, whose current package has a backend.

        `database` is None when the current package has no database.
        """
        database = _runtime_database(plugin, manifest)
        placement = PluginPlacement.objects.select_related("node").filter(plugin=plugin).first()
        if placement is None:
            return PluginRuntime(
                node=None,
                node_online=False,
                placement=None,
                desired_state="stopped",
                blocked_reason=None,
                database=database,
                outbound_hosts=list(manifest.outbound_hosts),
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
            database=database,
            outbound_hosts=list(manifest.outbound_hosts),
        )

    def restart(self, plugin: Plugin, manifest: PluginManifest, actor) -> PluginRuntime:
        """Ask the node to restart the plugin's process; a `failed` plugin starts provisioning again.

        Raises:
            PluginUninstallingError: The plugin is uninstalled or being deleted.
            PlacementNotFoundError: The plugin's backend has no placement.
        """
        with transaction.atomic():
            # The plugin first, as every lifecycle action locks it, so a restart never races
            # an uninstall.
            locked = lock_plugin(plugin.identifier)
            if locked is None:
                raise PluginNotFoundError()
            assert_plugin_in_service(locked)
            placement = PluginPlacement.objects.select_for_update().filter(plugin=plugin).first()
            if placement is None:
                raise PlacementNotFoundError()
            placement.restart_generation = F("restart_generation") + 1
            placement.save(update_fields=["restart_generation", "updated_at"])
            Plugin.objects.filter(pk=plugin.pk, state=PluginState.FAILED).update(
                state=PluginState.PROVISIONING, updated_at=timezone.now()
            )
            placement.refresh_from_db(fields=["restart_generation"])
            ActivityRecorder().restarted(actor, plugin.identifier, placement.restart_generation)
        log_restart(actor, plugin.identifier, placement.restart_generation)
        return self.runtime_of(plugin, manifest)


def _runtime_database(plugin: Plugin, manifest: PluginManifest) -> RuntimeDatabase | None:
    if manifest.database is None:
        return None
    record = PluginDatabase.objects.select_related("server").get(plugin=plugin)
    effective = plugin_limits(plugin, manifest).effective
    return RuntimeDatabase(
        record=record,
        connection_limit=effective["db_connections"],
        statement_timeout_seconds=effective["statement_timeout_seconds"],
        migrations_in_package=plugin.current_package.migration_count,
    )
