from collections.abc import Iterable

from rbac.models.enums import ResourceType
from tables.models import Graph, SubGraphNode
from tables.services.delete_services.base_delete_service import BaseDeleteService
from tables.services.delete_services.usage import (
    BucketCollector,
    UsageReport,
    build_reports,
)


class GraphDeleteService(BaseDeleteService):
    """Delete service for Graph: usage is the flows embedding it as a subgraph."""

    model = Graph

    def collect_usage(self, ids: list[int]) -> dict[int, UsageReport]:
        """Which flows embed each graph, limited to flows the caller may see."""
        flows = BucketCollector.for_resource(ResourceType.FLOWS, self.permissions)
        flows.add_rows(self._embedding_flow_rows(ids))
        return build_reports(ids, [flows])

    def _embedding_flow_rows(self, ids: list[int]) -> Iterable[tuple[int, int, str | None]]:
        """`(graph_id, parent_flow_id, parent_flow_name)` per embedding node."""
        if not ids:
            return []
        return SubGraphNode.objects.filter(
            subgraph_id__in=ids, graph__org_id=self.org_id
        ).values_list("subgraph_id", "graph_id", "graph__name")
