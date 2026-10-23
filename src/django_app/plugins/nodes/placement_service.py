from django.conf import settings

from plugins.exceptions import NoPluginNodeError, PluginNodeFullError
from plugins.models import Plugin, PluginNode, PluginPlacement


class PlacementService:
    """Puts a plugin's backend on a node, with a port and a Unix user id of its own."""

    def ensure_placement(self, plugin: Plugin) -> PluginPlacement:
        """Return the plugin's placement, creating it on the deployment's node the first time.

        The port and the user id are the lowest free ones in the node's ranges and stay the
        plugin's for its whole life. Must run inside a transaction: the node row is locked
        so two approvals cannot take the same port.

        Raises:
            NoPluginNodeError: No node named PLUGINS_NODE_NAME is registered.
            PluginNodeFullError: Every port or user id of the node is taken.
        """
        existing = PluginPlacement.objects.filter(plugin=plugin).first()
        if existing is not None:
            return existing
        node = (
            PluginNode.objects.select_for_update().filter(name=settings.PLUGINS_NODE_NAME).first()
        )
        if node is None:
            raise NoPluginNodeError()
        taken = list(node.placements.values_list("port", "unix_uid"))
        port = _lowest_free(node.port_range_start, node.port_range_end, {port for port, _ in taken})
        unix_uid = _lowest_free(
            node.uid_range_start, node.uid_range_end, {unix_uid for _, unix_uid in taken}
        )
        if port is None or unix_uid is None:
            raise PluginNodeFullError()
        return PluginPlacement.objects.create(
            plugin=plugin, node=node, port=port, unix_uid=unix_uid
        )


def _lowest_free(start: int, end: int, taken: set[int]) -> int | None:
    return next((number for number in range(start, end + 1) if number not in taken), None)
