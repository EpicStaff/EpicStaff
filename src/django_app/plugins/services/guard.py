"""Refuse to run anything a suspended plugin installed.

Hooked into the places every run passes through: starting a session (any trigger),
building an agent definition for a node payload, building a tool, and building a
Key-Value node. Each check costs one EXISTS query when no plugin is suspended anywhere.
"""

from collections.abc import Iterable

from tables.models import Graph

from plugins.exceptions import PluginSuspendedError
from plugins.models import Plugin
from plugins.resource_types import PluginResourceType


class PluginGuard:
    """Raise `PluginSuspendedError` when a row about to run belongs to a suspended plugin."""

    def check_flow(self, graph) -> None:
        """Refuse a flow that is, or transitively embeds as a subflow, a suspended plugin's flow.

        Called before the session row exists, so a refused run leaves no ERROR session.

        Raises:
            PluginSuspendedError: the flow or one of its subflows is suspended.
        """
        if not _any_suspended():
            return
        subflow_ids = Graph.objects.get_transitive_subflows(graph.pk).values_list("id", flat=True)
        self._check(PluginResourceType.FLOW, [graph.pk, *subflow_ids])

    def check_agent_definition(self, agent_definition_id: int) -> None:
        """Raises: PluginSuspendedError: the agent belongs to a suspended plugin."""
        if _any_suspended():
            self._check(PluginResourceType.AGENT_DEFINITION, [agent_definition_id])

    def check_tool(self, resource_type: PluginResourceType, tool_id: int) -> None:
        """Raises: PluginSuspendedError: the tool belongs to a suspended plugin."""
        if _any_suspended():
            self._check(resource_type, [tool_id])

    def check_key_value_table(self, table_id: int) -> None:
        """Refuse an org flow whose Key-Value node uses a suspended plugin's table.

        Raises:
            PluginSuspendedError: the table belongs to a suspended plugin.
        """
        if _any_suspended():
            self._check(PluginResourceType.KEY_VALUE_TABLE, [table_id])

    def _check(self, resource_type: PluginResourceType, object_ids: Iterable[int]) -> None:
        suspended = (
            Plugin.objects.filter(
                suspended=True,
                resources__resource_type=resource_type,
                resources__object_id__in=list(object_ids),
            )
            .values_list("name", flat=True)
            .first()
        )
        if suspended is not None:
            raise PluginSuspendedError(suspended)


def _any_suspended() -> bool:
    return Plugin.objects.filter(suspended=True).exists()


plugin_guard = PluginGuard()
