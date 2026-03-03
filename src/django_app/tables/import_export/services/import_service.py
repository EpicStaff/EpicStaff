from typing import List
from collections import defaultdict

from django.db import transaction

from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import EntityRegistry
from tables.import_export.enums import NodeType, EntityType
from tables.import_export.constants import DEPENDENCY_ORDER


class ImportService:
    def __init__(self, registry: EntityRegistry):
        self.registry = registry

    def import_data(self, export_data: dict, main_entity: str):
        id_mapper = IDMapper()

        with transaction.atomic():
            ordered_types = self._resolve_import_order(export_data)

            for entity_type in ordered_types:
                entities = export_data.get(entity_type, [])
                strategy = self.registry.get_strategy(entity_type)

                if entity_type == EntityType.GRAPH:
                    ordered_graphs = self._resolve_graph_order(entities)
                    for entity_data in ordered_graphs:
                        self._import_single_entity(
                            entity_data,
                            entity_type,
                            strategy,
                            id_mapper,
                            entity_type == main_entity,
                        )
                else:
                    for entity_data in entities:
                        self._import_single_entity(
                            entity_data,
                            entity_type,
                            strategy,
                            id_mapper,
                            entity_type == main_entity,
                        )

        return id_mapper

    def _resolve_import_order(self, export_data: dict) -> List[str]:
        """
        Topological sort based on dependencies.
        """
        # Entities will be imported from top to bottom based on this list
        sorted_keys = [
            entity_type
            for entity_type in DEPENDENCY_ORDER
            if entity_type in export_data
        ]

        return sorted_keys

    def _import_single_entity(
        self, entity_data, entity_type, strategy, id_mapper, is_main
    ):
        old_id = entity_data["id"]
        instance = strategy.import_entity(entity_data, id_mapper, is_main)
        id_mapper.map(entity_type, old_id, instance.id)

    def _resolve_graph_order(self, graphs: List[dict]) -> List[dict]:
        """
        Topological sort of graphs based on subgraph dependencies.
        Graphs that are used as subgraphs must be imported first.
        """
        graph_map = {graph["id"]: graph for graph in graphs}

        dependencies = defaultdict(set)

        for graph in graphs:
            subgraph_ids = self._extract_subgraph_ids(graph)
            for subgraph_id in subgraph_ids:
                if subgraph_id in graph_map:
                    dependencies[graph["id"]].add(subgraph_id)

        return self._topological_sort(graphs, dependencies)

    def _extract_subgraph_ids(self, graph_data: dict) -> List[int]:
        """Extract subgraph IDs from subgraph nodes"""
        subgraph_ids = []

        nodes = graph_data.get("nodes", [])
        for node in nodes:
            if node.get("node_type") == NodeType.SUBGRAPH_NODE and node.get("subgraph"):
                subgraph_ids.append(node["subgraph"])

        return subgraph_ids

    def _topological_sort(self, graphs: List[dict], dependencies: dict) -> List[dict]:
        """Sort graphs so dependencies come first"""
        graph_map = {graph["id"]: graph for graph in graphs}

        in_degree = defaultdict(int)
        for graph_id, deps in dependencies.items():
            in_degree[graph_id] = len(deps)

        queue = [graph for graph in graphs if in_degree[graph["id"]] == 0]
        sorted_graphs = []

        while queue:
            current = queue.pop(0)
            sorted_graphs.append(current)

            for graph_id, deps in dependencies.items():
                if current["id"] in deps:
                    deps.discard(current["id"])
                    in_degree[graph_id] -= 1
                    if in_degree[graph_id] == 0:
                        queue.append(graph_map[graph_id])

        if len(sorted_graphs) != len(graphs):
            raise ValueError("Circular graph dependency detected!")

        return sorted_graphs
