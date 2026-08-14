from __future__ import annotations

from tables.models.graph_models import TaskNode
from tables.services.base_node_payload_service import BaseNodePayloadService
from agents.services.node_surface_service import NodeSurfaceService
from src.shared.models import CombinedSurfaceData, TaskNodeData


class TaskNodePayloadService(BaseNodePayloadService):
    """Builds the fully-hydrated TaskNodeData payload consumed by the agent service.

    Single boundary for "everything the agent needs" for a task node: agent
    definition (with hydrated LLM credentials), and the tool/collection/s3
    resource pools derived from the node's combined surface.
    """

    def build_task_node_data(
        self,
        task_node: TaskNode,
        node_name: str,
        graph_id: int | None,
        session_id: int | None,
    ) -> TaskNodeData:
        combined_surface = CombinedSurfaceData(
            **NodeSurfaceService.build_combined_surface(task_node)
        )
        s3_files = self._build_s3_pool(combined_surface)

        return TaskNodeData(
            node_name=node_name,
            agent_definition=self._build_agent_definition_data(
                task_node.agent_definition
            ),
            instructions=task_node.instructions,
            input_map=task_node.input_map or {},
            output_variable_path=task_node.output_variable_path,
            output_schema=task_node.output_schema or {},
            remember_output=task_node.remember_output,
            surface=combined_surface,
            tools=self._build_tool_pool(
                combined_surface, graph_id, session_id, s3_files
            ),
            collections=self._build_collection_pool(combined_surface),
            s3_files=s3_files,
        )
