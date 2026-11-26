from collections import defaultdict, deque

from django.db import transaction
from loguru import logger
from proxies.sandbox.services import VenvService
from rbac.authorship import record_last_edits
from rbac.models import LastEditTrackedModel
from rbac.models.enums import Permission
from rest_framework.exceptions import PermissionDenied
from src.shared.models import UserAction
from user_audit.actor import Actor
from user_audit.context import mark_request_handled
from user_audit.recorder import record_user_action

from tables.import_export.archive import ImportArchive, InvalidArchiveError
from tables.import_export.constants import DEPENDENCY_ORDER
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.permissions import ENTITY_RESOURCE_MAP
from tables.import_export.preparation import prepare_import_data
from tables.import_export.registry import EntityRegistry
from tables.import_export.schemas import ImportSettings
from tables.import_export.strategies.source_collection import remove_restored_graph_indexes
from tables.services.storage_service.archive_unpacking.extraction_guard import ArchiveLimitExceeded
from tables.services.trigger_nodes import TriggerNodeInspector, trigger_node_access
from tables.validators.run_refusal_validator import assert_no_run_refusals_in_export
from tables.validators.top_level_node_list_validator import assert_no_top_level_node_lists


class ImportService:
    def __init__(self, registry: EntityRegistry):
        self.registry = registry

    def import_data(
        self,
        export_data: dict,
        main_entity: str,
        settings: ImportSettings = None,
        org_id: int | None = None,
        user=None,
        effective_permissions=None,
        archive: ImportArchive | None = None,
        actor: Actor | None = None,
        **strategy_kwargs,
    ):
        """Import `export_data` into `org_id`, `main_entity` being the file's main type.

        `effective_permissions=None` means a trusted internal caller: both permission
        checks (CREATE on each new resource, and USE for trigger nodes) are skipped.
        `strategy_kwargs` reach every strategy's `import_entity` as keyword arguments.

        Each main entity the file creates is recorded as a `created` user action by name
        (`updated` for one written over an existing row); dependencies it pulls in and
        entities it reuses are not. An import that creates nothing records nothing.

        Args:
            actor: Who the records name. None names the caller of the request being
                served; an import run outside a request (an import job) records
                nothing unless it names one.
        """
        if settings is None:
            settings = ImportSettings()
        mark_request_handled()

        id_mapper = IDMapper()
        denied_resources = set()
        assert_no_top_level_node_lists(export_data)
        export_data = prepare_import_data(export_data)
        # A trigger node in the file is live once created, so the whole import needs
        # flows:USE; refused here, before the transaction opens, so nothing is written.
        if effective_permissions is not None and TriggerNodeInspector.has_any_in_export(
            export_data
        ):
            trigger_node_access.assert_may_recreate(effective_permissions)
        # A flow crew would refuse to run is refused here, before anything is written.
        assert_no_run_refusals_in_export(export_data)
        created_resources: list[LastEditTrackedModel] = []
        # Venvs are created in the sandbox service, which the transaction does not
        # cover; a rollback has to undo them by hand.
        created_venv_ids: list[int] = []
        # Graph indexes are restored in the knowledge service, outside the transaction.
        created_graph_rag_ids: list[int] = []

        try:
            with transaction.atomic():
                ordered_types = self._resolve_import_order(export_data)

                for entity_type in ordered_types:
                    if not self.registry.has_strategy(entity_type):
                        logger.warning(
                            "Skipping unsupported entity type {} during import (no longer supported)",
                            entity_type,
                        )
                        continue

                    entities = export_data.get(entity_type, [])
                    strategy = self.registry.get_strategy(entity_type)

                    if entity_type == EntityType.GRAPH:
                        entities = self._resolve_graph_order(entities)

                    for entity_data in entities:
                        denied_resources |= self._import_single_entity(
                            entity_data,
                            entity_type,
                            strategy,
                            id_mapper,
                            entity_type == main_entity,
                            settings=settings,
                            org_id=org_id,
                            user=user,
                            effective_permissions=effective_permissions,
                            created_resources=created_resources,
                            created_venv_ids=created_venv_ids,
                            created_graph_rag_ids=created_graph_rag_ids,
                            archive=archive,
                            actor=actor,
                            **strategy_kwargs,
                        )

                if denied_resources:
                    names = ", ".join(sorted(r.value for r in denied_resources))
                    raise PermissionDenied(
                        f"Missing CREATE permission on: {names}. No changes were made."
                    )
                record_last_edits(created_resources, user)
        except Exception as error:
            VenvService().remove_upstream(created_venv_ids)
            remove_restored_graph_indexes(created_graph_rag_ids)
            if isinstance(error, ArchiveLimitExceeded):
                raise InvalidArchiveError(
                    {"code": "invalid_archive", "detail": str(error)}
                ) from error
            raise

        return id_mapper, self.registry

    def _resolve_import_order(self, export_data: dict) -> list[str]:
        """
        Topological sort based on dependencies.
        """
        # Entities will be imported from top to bottom based on this list
        sorted_keys = [
            entity_type for entity_type in DEPENDENCY_ORDER if entity_type in export_data
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
        *,
        created_resources: list[LastEditTrackedModel],
        actor: Actor | None,
        **kwargs,
    ):
        old_id = entity_data["id"]

        existing = None
        if not is_main or strategy.reuse_when_main:
            existing = strategy.find_existing(entity_data, id_mapper, org_id=org_id)

        was_created = existing is None

        denied = set()
        if was_created and effective_permissions is not None:
            for created_type in (entity_type, *strategy.nested_entity_types(entity_data)):
                resource = ENTITY_RESOURCE_MAP.get(created_type)
                if resource is not None and not effective_permissions.can(
                    resource, Permission.CREATE
                ):
                    denied.add(resource)

        kwargs["org_id"] = org_id
        kwargs["user"] = user

        instance = strategy.import_entity(
            entity_data, id_mapper, is_main, settings=settings, **kwargs
        )
        if instance is None:
            return denied
        if was_created and isinstance(instance, LastEditTrackedModel):
            created_resources.append(instance)
        # Some strategies (e.g. GraphStrategy) register their own mapping
        # at creation time so downstream logic within the same
        # create_entity call can resolve it. Don't overwrite that mapping.
        if not id_mapper.has_mapping(entity_type, old_id):
            id_mapper.map(entity_type, old_id, instance.pk, was_created)
        if is_main and id_mapper.was_created(entity_type, old_id):
            record_user_action(
                action=(
                    UserAction.UPDATED
                    if id_mapper.was_replaced(entity_type, old_id)
                    else UserAction.CREATED
                ),
                org_id=org_id,
                target=instance,
                actor=actor,
            )
        return denied

    def _resolve_graph_order(self, graphs: list[dict]) -> list[dict]:
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

    def _extract_subgraph_ids(self, graph_data: dict) -> list[int]:
        """Extract subgraph IDs from subgraph nodes"""
        subgraph_ids = []

        nodes = graph_data.get("nodes", [])
        for node in nodes:
            if node.get("node_type") == NodeType.SUBGRAPH_NODE and node.get("subgraph"):
                subgraph_ids.append(node["subgraph"])

        return subgraph_ids

    def _topological_sort(self, graphs: list[dict], dependencies: dict) -> list[dict]:
        """Sort graphs so dependencies come first.

        Kahn's algorithm over a reverse-dependency map, so the cost is linear in the
        number of flows and subgraph references: an import file may hold a very large
        number of flows, and this runs inside the import transaction.

        Flows with no dependency keep file order; a flow is placed as soon as everything
        it uses is placed, and flows unblocked by the same flow keep file order.
        """
        graph_map = {graph["id"]: graph for graph in graphs}

        dependents = defaultdict(list)
        in_degree = defaultdict(int)
        for graph_id, deps in dependencies.items():
            in_degree[graph_id] = len(deps)
            for dependency_id in deps:
                dependents[dependency_id].append(graph_id)

        queue = deque(graph for graph in graphs if in_degree[graph["id"]] == 0)
        sorted_graphs = []

        while queue:
            current = queue.popleft()
            sorted_graphs.append(current)

            # Popped, not read: a file that repeats a flow id must unblock its
            # dependents once, not once per copy.
            for dependent_id in dependents.pop(current["id"], ()):
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(graph_map[dependent_id])

        if len(sorted_graphs) != len(graphs):
            raise ValueError("Circular graph dependency detected!")

        return sorted_graphs
