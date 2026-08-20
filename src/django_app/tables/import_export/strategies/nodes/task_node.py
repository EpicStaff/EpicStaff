from typing import Optional

from django.core.exceptions import ObjectDoesNotExist

from agents.models import InlineSurface, InlineSurfacePythonTool, InlineSurfaceMcpTool
from tables.models import TaskNode
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.strategies.nodes.inline_surface_helpers import (
    assign_node_surface_list,
    create_inline_surface,
)
from tables.import_export.serializers.task_node import TaskNodeImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class TaskNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.TASK_NODE
    serializer_class = TaskNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[TaskNode]:
        return TaskNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: TaskNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: TaskNode) -> dict:
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

    def export_entity(self, instance: TaskNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> TaskNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        surface_ids = data.pop("surface_list", [])
        inline_surface_data = data.pop("inline_surface", None)
        old_agent_definition_id = data.pop("agent_definition", None)

        data["agent_definition"] = id_mapper.get_or_none(
            EntityType.AGENT_DEFINITION, old_agent_definition_id
        )

        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        task_node = serializer.save()

        assign_node_surface_list(task_node, surface_ids, id_mapper)
        create_inline_surface(
            InlineSurface,
            {"task_node": task_node},
            InlineSurfacePythonTool,
            InlineSurfaceMcpTool,
            "inline_surface",
            inline_surface_data,
            id_mapper,
        )

        return task_node
