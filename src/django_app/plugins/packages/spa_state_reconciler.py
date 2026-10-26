"""Puts each plugin's served frontend back in line with its state, every minute.

The flag nginx reads for the maintenance page, and the `current` link it serves, are written
after a transaction commits (`SpaPublisher`); a write that fails there is logged and left. This
repairs both from the plugins' rows: the flag exists exactly for plugins in maintenance, and a
running (or failed) plugin with a frontend serves its current version once that version's
files are there. It never removes a directory, and never waits for a plugin another
transaction holds (an approval writes its files under the plugin's lock): that plugin is left
to the next pass.
"""

from django.conf import settings
from django.db import transaction
from utils.logger import logger

from plugins.audit import log_spa_repaired
from plugins.lifecycle.lifecycle_locks import lock_plugin
from plugins.models import Plugin, PluginState
from plugins.packages.spa_publisher import SpaPublisher

_SERVING_STATES = (PluginState.RUNNING, PluginState.FAILED)


class SpaStateReconciler:
    def __init__(self, publisher: SpaPublisher | None = None):
        self._publisher = publisher or SpaPublisher()

    def run(self) -> int:
        """Repair every plugin whose flag or `current` is wrong; returns how many repairs.

        One query, whatever the number of plugins, plus one for each plugin whose files do not
        match it. A plugin whose files cannot be repaired is logged and the others go on; one
        another transaction holds is skipped. Nothing happens while the SPA volume is not
        mounted.
        """
        if not settings.PLUGINS_SPA_ROOT.is_dir():
            return 0
        repairs = 0
        plugins = Plugin.objects.select_related("current_package").only(
            "identifier", "state", "current_package__version", "current_package__spa_file_count"
        )
        for plugin in plugins:
            try:
                if self._repairs_needed(plugin):
                    repairs += self._repair_locked(plugin.identifier)
            except OSError:
                logger.exception(
                    "Could not repair the published frontend of {identifier}",
                    identifier=plugin.identifier,
                )
        return repairs

    def _repair_locked(self, identifier: str) -> int:
        """Repair one plugin from its row as it is now, read and written under its lock.

        A lifecycle change writes the flag and `current` only after its transaction commits.
        Holding the plugin's lock while reading the row and writing the files means no change
        commits in between: one that committed before is read here, and one that commits after
        writes its own files last. Either way the files end as the latest state says. A plugin
        whose lock another transaction holds is skipped, not waited for: this runs in the
        retention loop, which an approval writing files under that lock must not hold up.
        """
        with transaction.atomic():
            plugin = lock_plugin(identifier, skip_locked=True)
            if plugin is None:
                return 0
            return self._repair(plugin)

    def _repairs_needed(self, plugin: Plugin) -> bool:
        return self._flag_wrong(plugin) or self._current_wrong(plugin)

    def _repair(self, plugin: Plugin) -> int:
        identifier = plugin.identifier
        repairs = 0
        if self._flag_wrong(plugin):
            self._publisher.set_maintenance(identifier, plugin.state == PluginState.MAINTENANCE)
            log_spa_repaired(identifier, "maintenance_flag")
            repairs += 1
        if self._current_wrong(plugin):
            self._publisher.switch_current(identifier, plugin.current_package.version)
            log_spa_repaired(identifier, "current")
            repairs += 1
        return repairs

    def _flag_wrong(self, plugin: Plugin) -> bool:
        in_maintenance = plugin.state == PluginState.MAINTENANCE
        return self._publisher.maintenance_flag_set(plugin.identifier) != in_maintenance

    def _current_wrong(self, plugin: Plugin) -> bool:
        package = plugin.current_package
        return (
            plugin.state in _SERVING_STATES
            and package is not None
            and package.spa_file_count > 0
            and self._publisher.current_version(plugin.identifier) != package.version
            and self._publisher.has_version(plugin.identifier, package.version)
        )
