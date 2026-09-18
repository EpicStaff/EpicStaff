from typing import Optional

from django.core.exceptions import ObjectDoesNotExist

from agents.models import (
    AgentInlineSurface,
    AgentInlineSurfacePythonTool,
    AgentInlineSurfaceMcpTool,
)
from tables.models import AgentNode
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.strategies.nodes.inline_surface_helpers import (
    assign_node_surface_list,
    create_agent_node_tasks,
    create_inline_surface,
)
from tables.import_export.serializers.agent_node import AgentNodeImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class AgentNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.AGENT_NODE
    serializer_class = AgentNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[AgentNode]:
        return AgentNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: AgentNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: AgentNode) -> dict:
        deps = {EntityType.GRAPH: [instance.graph_id]}

        if instance.agent_definition_id:
            deps[EntityType.AGENT_DEFINITION] = [instance.agent_definition_id]

        deps[EntityType.SURFACE] = list(
            instance.surface_list.values_list("id", flat=True)
        )

        try:
            inline_surface = instance.inline_surface
        except ObjectDoesNotExist:
            inline_surface = None

        if inline_surface:
            deps[EntityType.PYTHON_CODE_TOOL] = list(
                inline_surface.python_tools.values_list("python_tool_id", flat=True)
            )
            deps[EntityType.MCP_TOOL] = list(
                inline_surface.mcp_tools.values_list("mcp_tool_id", flat=True)
            )

        return deps

    def export_entity(self, instance: AgentNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> AgentNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        surface_ids = data.pop("surface_list", [])
        inline_surface_data = data.pop("inline_surface", None)
        tasks_data = data.pop("tasks", [])
        old_agent_definition_id = data.pop("agent_definition", None)

        data["agent_definition"] = id_mapper.get_or_none(
            EntityType.AGENT_DEFINITION, old_agent_definition_id
        )

        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        agent_node = serializer.save()

        assign_node_surface_list(agent_node, surface_ids, id_mapper)
        create_inline_surface(
            AgentInlineSurface,
            {"agent_node": agent_node},
            AgentInlineSurfacePythonTool,
            AgentInlineSurfaceMcpTool,
            "agent_inline_surface",
            inline_surface_data,
            id_mapper,
        )
        create_agent_node_tasks(agent_node, tasks_data)

        return agent_node
