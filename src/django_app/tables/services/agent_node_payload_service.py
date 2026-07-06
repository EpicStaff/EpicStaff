from __future__ import annotations

from tables.models.graph_models import AgentNode
from tables.services.base_node_payload_service import BaseNodePayloadService
from tables.services.node_surface_service import NodeSurfaceService
from src.shared.models import AgentNodeData, AgentNodeTaskData, CombinedSurfaceData


class AgentNodePayloadService(BaseNodePayloadService):
    """Builds the fully-hydrated AgentNodeData payload consumed by the agent service.

    Single boundary for "everything the agent needs" for an agent node: agent
    definition (with hydrated LLM credentials), the tool/collection/s3
    resource pools derived from the node's combined surface, and its ordered
    sub-tasks with context resolved to task names.
    """

    def build_agent_node_data(
        self,
        agent_node: AgentNode,
        node_name: str,
        graph_id: int | None,
        session_id: int | None,
    ) -> AgentNodeData:
        combined_surface = CombinedSurfaceData(
            **NodeSurfaceService.build_combined_surface(agent_node)
        )

        return AgentNodeData(
            node_name=node_name,
            agent_definition=self._build_agent_definition_data(
                agent_node.agent_definition
            ),
            input_map=agent_node.input_map or {},
            surface=combined_surface,
            tools=self._build_tool_pool(combined_surface, graph_id, session_id),
            collections=self._build_collection_pool(combined_surface),
            s3_files=self._build_s3_pool(combined_surface),
            tasks=[
                AgentNodeTaskData(
                    name=task.name,
                    order=task.order,
                    instructions=task.instructions,
                    output_schema=task.output_schema or {},
                    context_tasks=[
                        context_task.name for context_task in task.context_tasks.all()
                    ],
                )
                for task in agent_node.tasks.all()
            ],
        )
