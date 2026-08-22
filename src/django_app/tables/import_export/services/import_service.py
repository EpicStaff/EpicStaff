from typing import List
from collections import defaultdict

from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import EntityRegistry
from tables.import_export.enums import NodeType, EntityType
from tables.import_export.constants import DEPENDENCY_ORDER
from tables.import_export.schemas import ImportSettings
from tables.import_export.permissions import ENTITY_RESOURCE_MAP
from tables.models.rbac_models.rbac_enums import Permission


class ImportService:
    def __init__(self, registry: EntityRegistry):
        self.registry = registry

    def import_data(
        self,
        export_data: dict,
        main_entity: str,
        settings: ImportSettings = None,
        org_id: int = None,
        user=None,
        effective_permissions=None,
    ):
        if settings is None:
            settings = ImportSettings()

        id_mapper = IDMapper()
        denied_resources = set()

        with transaction.atomic():
            ordered_types = self._resolve_import_order(export_data)

            for entity_type in ordered_types:
                entities = export_data.get(entity_type, [])
                strategy = self.registry.get_strategy(entity_type)

                if entity_type == EntityType.GRAPH:
                    entities = self._resolve_graph_order(entities)

                for entity_data in entities:
                    denied = self._import_single_entity(
                        entity_data,
                        entity_type,
                        strategy,
                        id_mapper,
                        entity_type == main_entity,
                        settings=settings,
                        org_id=org_id,
                        user=user,
                        effective_permissions=effective_permissions,
                    )
                    if denied is not None:
                        denied_resources.add(denied)

            if denied_resources:
                names = ", ".join(sorted(r.value for r in denied_resources))
                raise PermissionDenied(
                    f"Missing CREATE permission on: {names}. No changes were made."
                )

        return id_mapper, self.registry

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
        self,
        entity_data,
        entity_type,
        strategy,
        id_mapper,
        is_main,
        settings: ImportSettings = None,
        org_id=None,
        user=None,
        effective_permissions=None,
        **kwargs,
    ):
        old_id = entity_data["id"]

        existing = None
        if not is_main:
            existing = strategy.find_existing(entity_data, id_mapper, org_id=org_id)

        was_created = existing is None

        denied = None
        if was_created and effective_permissions is not None:
            resource = ENTITY_RESOURCE_MAP.get(entity_type)
            if resource is not None and not effective_permissions.can(
                resource, Permission.CREATE
            ):
                denied = resource

        kwargs["org_id"] = org_id
        kwargs["user"] = user

        instance = strategy.import_entity(
            entity_data, id_mapper, is_main, settings=settings, **kwargs
        )
        if instance is None:
            return denied
        # Some strategies (e.g. GraphStrategy) register their own mapping
        # at creation time so downstream logic within the same
        # create_entity call can resolve it. Don't overwrite that mapping.
        if not id_mapper.has_mapping(entity_type, old_id):
            id_mapper.map(entity_type, old_id, instance.id, was_created)
        return denied

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
