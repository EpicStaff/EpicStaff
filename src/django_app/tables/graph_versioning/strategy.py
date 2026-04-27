from tables.import_export.strategies.graph import GraphStrategy
from tables.models import Graph


class GraphVersioningStrategy:
    """
    Reuses GraphStrategy's serialization to produce a graph-only snapshot
    for versioning purposes. No dependency tree traversal.
    """

    def __init__(self):
        self._graph_strategy = GraphStrategy()

    def create_snapshot(self, graph: Graph) -> dict:
        """
        Serialize the graph's internal state (metadata, nodes, edges,
        conditional edges) into a JSON-serializable dict.
        """
        return self._graph_strategy.export_entity(graph)

    def collect_dependencies(self, graph: Graph) -> dict:
        """
        Build a lightweight manifest of external dependency IDs
        the graph currently references. No full serialization — just IDs.
        """
        raw_deps = self._graph_strategy.extract_dependencies_from_instance(graph)
        light_deps = {
            str(entity_type.value): list(ids)
            for entity_type, ids in raw_deps.items()
            if ids
        }
        return light_deps
