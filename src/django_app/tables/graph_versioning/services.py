from tables.models import GraphVersion
from tables.graph_versioning.strategy import GraphVersioningStrategy
from tables.models import Graph


class GraphVersioningService:
    def __init__(self):
        self._strategy = GraphVersioningStrategy()

    def save_version(
        self, graph: Graph, name: str, description: str = ""
    ) -> GraphVersion:
        """
        Create a named version snapshot of the given graph.
        """
        snapshot = self._strategy.create_snapshot(graph)
        light_deps = self._strategy.collect_dependencies(graph)

        return GraphVersion.objects.create(
            graph=graph,
            name=name,
            description=description,
            snapshot=snapshot,
            dependencies=light_deps,
        )
