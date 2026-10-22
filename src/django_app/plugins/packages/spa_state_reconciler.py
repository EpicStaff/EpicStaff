"""Puts each plugin's served frontend back in line with its state, every minute.

The flag nginx reads for the maintenance page, and the `current` link it serves, are written
after a transaction commits (`SpaPublisher`); a write that fails there is logged and left. This
repairs both from the plugins' rows: the flag exists exactly for plugins in maintenance, and a
running (or failed) plugin with a frontend serves its current version once that version's
files are there. It never removes a directory.
"""

from django.conf import settings
from utils.logger import logger

from plugins.audit import log_spa_repaired
from plugins.models import Plugin, PluginState
from plugins.packages.spa_publisher import SpaPublisher

_SERVING_STATES = (PluginState.RUNNING, PluginState.FAILED)


class SpaStateReconciler:
    def __init__(self, publisher: SpaPublisher | None = None):
        self._publisher = publisher or SpaPublisher()

    def run(self) -> int:
        """Repair every plugin whose flag or `current` is wrong; returns how many repairs.

        One query, whatever the number of plugins. A plugin whose files cannot be repaired is
        logged and the others go on. Nothing happens while the SPA volume is not mounted.
        """
        if not settings.PLUGINS_SPA_ROOT.is_dir():
            return 0
        repairs = 0
        plugins = Plugin.objects.select_related("current_package").only(
            "identifier", "state", "current_package__version", "current_package__spa_file_count"
        )
        for plugin in plugins:
            try:
                repairs += self._repair(plugin)
            except OSError:
                logger.exception(
                    "Could not repair the published frontend of {identifier}",
                    identifier=plugin.identifier,
                )
        return repairs

    def _repair(self, plugin: Plugin) -> int:
        identifier = plugin.identifier
        repairs = 0
        in_maintenance = plugin.state == PluginState.MAINTENANCE
        if self._publisher.maintenance_flag_set(identifier) != in_maintenance:
            self._publisher.set_maintenance(identifier, in_maintenance)
            log_spa_repaired(identifier, "maintenance_flag")
            repairs += 1
        package = plugin.current_package
        if (
            plugin.state in _SERVING_STATES
            and package is not None
            and package.spa_file_count > 0
            and self._publisher.current_version(identifier) != package.version
            and self._publisher.has_version(identifier, package.version)
        ):
            self._publisher.switch_current(identifier, package.version)
            log_spa_repaired(identifier, "current")
            repairs += 1
        return repairs
