"""The Runtime tab: where a plugin's backend runs, what its node last saw, its database, its
outbound hosts, and restarts."""

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from epicstaff_plugin.contracts.manifest import OutboundHost

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_restart
from plugins.configuration.limits import plugin_limits
from plugins.configuration.setting_values import blocked_reason
from plugins.exceptions import PlacementNotFoundError, PluginNotFoundError, PluginUpgradeOpenError
from plugins.lifecycle.lifecycle_locks import lock_plugin
from plugins.lifecycle.plugin_actions import assert_plugin_in_service
from plugins.models import (
    Plugin,
    PluginDatabase,
    PluginNode,
    PluginPackage,
    PluginPlacement,
    PluginState,
)

# A node reports every 10 s; three missed reports make it offline.
NODE_ONLINE_WINDOW = timedelta(seconds=30)


@dataclass(frozen=True)
class RuntimeDatabase:
    """A plugin's database record, with the limits its app role gets now."""

    record: PluginDatabase
    connection_limit: int
    statement_timeout_seconds: int
    migrations_in_package: int
    """How many migrations the package the node runs holds."""


@dataclass(frozen=True)
class PluginRuntime:
    """What the Runtime tab shows. `upgrade` is `{from_version, to_version}` exactly while the
    node runs a package other than the current one (an upgrade's target)."""

    node: PluginNode | None
    node_online: bool
    placement: PluginPlacement | None
    desired_state: str
    blocked_reason: str | None
    database: RuntimeDatabase | None
    outbound_hosts: list[OutboundHost]
    upgrade: dict[str, str] | None = None


class PluginRuntimeService:
    def runtime_of(self, plugin: Plugin, package: PluginPackage) -> PluginRuntime:
        """What the Runtime tab shows of `plugin`, whose node package `package` has a backend.

        `database` is None when that package has no database.
        """
        manifest = package.parsed_manifest
        database = _runtime_database(plugin, package)
        upgrade = (
            {"from_version": plugin.current_package.version, "to_version": package.version}
            if package.pk != plugin.current_package_id
            else None
        )
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
                upgrade=upgrade,
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
            upgrade=upgrade,
        )

    def restart(self, plugin: Plugin, package: PluginPackage, actor) -> PluginRuntime:
        """Ask the node to restart the plugin's process; a `failed` plugin starts provisioning again.

        While an upgrade is being prepared, this restarts the running version.

        Raises:
            PluginUninstallingError: The plugin is uninstalled or being deleted.
            PluginUpgradeOpenError: The plugin is stopped for an upgrade.
            PlacementNotFoundError: The plugin's backend has no placement.
        """
        with transaction.atomic():
            # The plugin first, as every lifecycle action locks it, so a restart never races
            # an uninstall.
            locked = lock_plugin(plugin.identifier)
            if locked is None:
                raise PluginNotFoundError()
            assert_plugin_in_service(locked)
            if locked.state == PluginState.MAINTENANCE:
                raise PluginUpgradeOpenError()
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
        return self.runtime_of(plugin, package)


def _runtime_database(plugin: Plugin, package: PluginPackage) -> RuntimeDatabase | None:
    manifest = package.parsed_manifest
    if manifest.database is None:
        return None
    record = PluginDatabase.objects.select_related("server").get(plugin=plugin)
    effective = plugin_limits(plugin, manifest).effective
    return RuntimeDatabase(
        record=record,
        connection_limit=effective["db_connections"],
        statement_timeout_seconds=effective["statement_timeout_seconds"],
        migrations_in_package=package.migration_count,
    )
