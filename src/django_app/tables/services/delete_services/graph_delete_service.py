from collections.abc import Iterable

from tables.models import Graph, SubGraphNode
from tables.models.rbac_models.rbac_enums import ResourceType
from tables.services.delete_services.base_delete_service import BaseDeleteService
from tables.services.delete_services.usage import (
    BucketCollector,
    RefKind,
    UsageReport,
    build_reports,
)
from tables.services.rbac.effective_permissions import EffectivePermissions


class GraphDeleteService(BaseDeleteService):
    """Delete service for Graph (Flow) entities.

    A graph is referenced from exactly one place in the schema --
    `SubGraphNode.subgraph`, i.e. another flow embedding it as a subgraph -- so
    it reports a single FLOWS bucket. The bucket list still exists because the
    shape is shared with entities that genuinely have several.

    Graph is a soft-delete root, so `BaseDeleteService._delete_rows` removes its
    rows one at a time; a queryset delete would bypass `SoftDeleteMixin.delete`
    and destroy them outright.
    """

    model = Graph

    def collect_usage(
        self, ids: list[int], org_id: int, effective: EffectivePermissions
    ) -> dict[int, UsageReport]:
        """Which flows embed each graph, limited to flows the caller may see."""
        flows = BucketCollector.for_resource(ResourceType.FLOWS, effective)
        flows.add_rows(self._embedding_flow_rows(ids, org_id), kind=RefKind.FLOW)
        return build_reports(ids, [flows])

    @staticmethod
    def _embedding_flow_rows(
        ids: list[int], org_id: int
    ) -> Iterable[tuple[int, int, str | None]]:
        """`(graph_id, parent_flow_id, parent_flow_name)` per embedding node.

        One parent flow embedding the same subgraph through two SubGraphNodes
        yields two rows; the collector folds them into one reference.
        """
        if not ids:
            return []
        return SubGraphNode.objects.filter(
            subgraph_id__in=ids, graph__org_id=org_id
        ).values_list("subgraph_id", "graph_id", "graph__name")
