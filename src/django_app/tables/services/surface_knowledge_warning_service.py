from __future__ import annotations

from agents.services.node_surface_service import NodeSurfaceService
from tables.models.graph_models import AgentNode, BaseNode, Graph, TaskNode
from tables.models.knowledge_models.collection_models import SourceCollection
from src.shared.models import CombinedSurfaceData, CombinedSurfaceKnowledgeData

_SURFACE_PREFETCH_FIELDS = (
    "surface_list__python_tools",
    "surface_list__mcp_tools",
    "surface_list__storage_items",
    "surface_list__knowledge__naive_search_config",
    "surface_list__knowledge__graph_basic_search_config",
    "surface_list__knowledge__graph_local_search_config",
    "surface_list__knowledge__graph_global_search_config",
    "surface_list__knowledge__graph_drift_search_config",
    "inline_surface__python_tools",
    "inline_surface__mcp_tools",
    "inline_surface__storage_items",
    "inline_surface__knowledge__naive_search_config",
    "inline_surface__knowledge__graph_basic_search_config",
    "inline_surface__knowledge__graph_local_search_config",
    "inline_surface__knowledge__graph_global_search_config",
    "inline_surface__knowledge__graph_drift_search_config",
)


class SurfaceKnowledgeWarningService:
    """Flags surfaces whose knowledge collection has no search config set.

    Mirrors BaseNodePayloadService._build_collection_spec exactly: a
    CombinedSurfaceKnowledgeData entry with all search-config fields None is
    silently dropped there, so it must be surfaced here as a session-start
    warning instead.
    """

    def build_warnings(self, graph: Graph) -> list[dict]:
        task_node_list = TaskNode.objects.filter(graph=graph).prefetch_related(
            *_SURFACE_PREFETCH_FIELDS
        )
        agent_node_list = AgentNode.objects.filter(graph=graph).prefetch_related(
            *_SURFACE_PREFETCH_FIELDS
        )

        unconfigured_entries = self._collect_unconfigured_entries(
            task_node_list
        ) + self._collect_unconfigured_entries(agent_node_list)

        collection_names = self._resolve_collection_names(unconfigured_entries)

        return [
            self._build_warning(node, knowledge, collection_names)
            for node, knowledge in unconfigured_entries
        ]

    def _collect_unconfigured_entries(
        self, node_list
    ) -> list[tuple[BaseNode, CombinedSurfaceKnowledgeData]]:
        entries: list[tuple[BaseNode, CombinedSurfaceKnowledgeData]] = []

        for node in node_list:
            combined_surface = CombinedSurfaceData(
                **NodeSurfaceService.build_combined_surface(node)
            )
            for knowledge in combined_surface.knowledge:
                if self._has_no_search_config(knowledge):
                    entries.append((node, knowledge))

        return entries

    def _has_no_search_config(self, knowledge: CombinedSurfaceKnowledgeData) -> bool:
        return (
            knowledge.naive_search_config is None
            and knowledge.graph_basic_search_config is None
            and knowledge.graph_local_search_config is None
            and knowledge.graph_global_search_config is None
            and knowledge.graph_drift_search_config is None
        )

    def _resolve_collection_names(
        self, entries: list[tuple[BaseNode, CombinedSurfaceKnowledgeData]]
    ) -> dict[int, str]:
        collection_ids = {knowledge.collection for _, knowledge in entries}
        return dict(
            SourceCollection.objects.filter(pk__in=collection_ids).values_list(
                "pk", "collection_name"
            )
        )

    def _build_warning(
        self,
        node: BaseNode,
        knowledge: CombinedSurfaceKnowledgeData,
        collection_names: dict[int, str],
    ) -> dict:
        node_name = node.node_name or node.__class__.__name__
        collection_name = collection_names.get(knowledge.collection)
        collection_label = collection_name or f"#{knowledge.collection}"

        return {
            "type": "knowledge_collection_without_search_config",
            "node_id": node.id,
            "node_name": node_name,
            "node_type": node.__class__.__name__,
            "collection_id": knowledge.collection,
            "collection_name": collection_name,
            "reason": (
                f"Collection '{collection_label}' attached to '{node_name}' has "
                "no search configuration set and will not be available to the agent."
            ),
        }
