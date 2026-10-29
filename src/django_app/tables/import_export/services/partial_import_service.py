from copy import deepcopy
from dataclasses import dataclass

from django.db import transaction
from loguru import logger
from proxies.sandbox.services import VenvService
from rbac.authorship import record_last_edits
from rbac.models import LastEditTrackedModel
from rbac.models.enums import Permission
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from tables.import_export.constants import DEPENDENCY_ORDER, NODE_MAPPING_KEY
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.permissions import ENTITY_RESOURCE_MAP
from tables.import_export.preparation import prepare_import_data
from tables.import_export.registry import EntityRegistry
from tables.import_export.strategies.graph import GraphStrategy
from tables.models import Graph
from tables.serializers.model_serializers.graph_serializers import GraphSerializer
from tables.services.trigger_nodes import TriggerNodeInspector, trigger_node_access
from tables.utils.legacy_node_number import move_legacy_badge_into_node_number

# Node entity types that belong to a graph — handled via recreate_graph_children.
# Start/end nodes are intentionally excluded: they are structural and every
# graph already has them, so they are not part of partial export/import.
_NODE_ENTITY_TYPES = {
    EntityType.CREW_NODE,
    EntityType.PYTHON_NODE,
    EntityType.AUDIO_TRANSCRIPTION_NODE,
    EntityType.FILE_EXTRACTOR_NODE,
    EntityType.KEY_VALUE_NODE,
    EntityType.TELEGRAM_TRIGGER_NODE,
    EntityType.WEBHOOK_TRIGGER_NODE,
    EntityType.DECISION_TABLE_NODE,
    EntityType.CLASSIFICATION_DECISION_TABLE_NODE,
    EntityType.SUBGRAPH_NODE,
    EntityType.NOTE_NODE,
    EntityType.SCHEDULE_TRIGGER_NODE,
    EntityType.KNOWLEDGE_NODE,
    EntityType.AGENT_NODE,
    EntityType.TASK_NODE,
}


@dataclass(frozen=True)
class PartialImportResult:
    """Outcome of a partial import.

    `id_mapper` maps the file's dependency ids to the rows used in the active org.
    `content` holds the file's nodes and the edges between them in the shape of
    `GET /graphs/{id}/` (every `GraphSerializer` node list plus `edge_list`). None of
    it exists in the database: the client adds it to the canvas, and the flow save
    persists it.
    """

    id_mapper: IDMapper
    content: dict


class PartialImportService:
    """
    Import the output of GraphPartialExportService (partial-export) against an
    existing graph identified by graph_id.

    The export file contains standalone nodes (with their transitive
    dependencies) and optionally edges. Dependencies are created (or reused) in
    the active org and committed. Nodes and edges are NOT written to the graph:
    they are returned as unsaved content, with ids remapped via IDMapper, for the
    client to place on the canvas and persist through the flow save.
    """

    def __init__(self, registry: EntityRegistry):
        self.registry = registry

    def import_data(
        self,
        export_data: dict,
        graph: Graph,
        org_id: int | None = None,
        user=None,
        effective_permissions=None,
        serializer_context: dict | None = None,
    ) -> PartialImportResult:
        """Create the file's dependencies and return its nodes and edges unsaved.

        The target graph is left untouched: no nodes, edges, node numbers, version or
        last edit. Dependencies created here stay even if the client discards the
        returned content.

        Args:
            graph: Graph the nodes are prepared for. Nodes are validated against it
                and numbered from its counter, but not added to it.
            effective_permissions: `None` means a trusted internal caller: both
                permission checks (CREATE on new dependencies, and USE for trigger
                nodes) are skipped.
            serializer_context: Context for the read serializers rendering
                `content`, normally the view's serializer context.
        """
        nodes_data = self._collect_nodes(export_data)
        if not nodes_data:
            raise ValidationError({"detail": "No nodes found in the import file."})

        id_mapper = IDMapper()
        export_data = prepare_import_data(export_data)
        # A trigger node among the imported nodes is live once saved, so the import
        # needs flows:USE; refused here, before the transaction opens, so nothing is
        # written. Only the collected node entries are imported, so only they count.
        if effective_permissions is not None and TriggerNodeInspector.has_any_in_node_entries(
            nodes_data
        ):
            trigger_node_access.assert_may_recreate(effective_permissions)

        # Venvs are created in the sandbox service, which the transaction does not
        # cover; a rollback has to undo them by hand.
        created_venv_ids: list[int] = []

        try:
            with transaction.atomic():
                # Step 1: import non-node dependencies (LLM configs, crews, etc.)
                # into the active org, enforcing per-resource CREATE permission.
                created_dependencies = self._import_dependencies(
                    export_data,
                    id_mapper,
                    org_id=org_id,
                    user=user,
                    effective_permissions=effective_permissions,
                    created_venv_ids=created_venv_ids,
                )
                record_last_edits(created_dependencies, user)

                # Step 2: create the nodes and edges in the target graph, render them, then
                # roll them back. Creating them runs every node strategy's validation,
                # reference remapping and normalization, and lets the response reuse the
                # exact GET-graph serializers; rolling back persists none of it (nodes,
                # edges, node-number counter, node last edits). The user persists the
                # content by saving the flow, and "exit without saving" discards it.
                # Do not replace this with in-memory conversion: it would duplicate each
                # node strategy and drift from it.
                graph_strategy: GraphStrategy = self.registry.get_strategy(EntityType.GRAPH)
                with transaction.atomic():
                    node_mapper = graph_strategy.recreate_graph_children(
                        graph,
                        {
                            "nodes": nodes_data,
                            "edge_list": export_data.get("edge_list", []),
                        },
                        id_mapper,
                        is_partial=True,
                        user=user,
                    )
                    content = self._serialize_content(
                        graph,
                        set(node_mapper.get_new_ids(NODE_MAPPING_KEY)),
                        serializer_context or {},
                    )
                    transaction.set_rollback(True)
        except Exception:
            VenvService().remove_upstream(created_venv_ids)
            raise

        return PartialImportResult(id_mapper=id_mapper, content=content)

    @staticmethod
    def _serialize_content(graph: Graph, new_node_ids: set[int], context: dict) -> dict:
        """Render the new nodes, and the edges between them, as `GET /graphs/{id}/` does."""
        graph_fields = GraphSerializer(context=context).fields
        content = {}
        for list_key, field in graph_fields.items():
            if not isinstance(field, serializers.ListSerializer):
                continue
            related_rows = getattr(graph, field.source).all()
            if list_key == "edge_list":
                rows = related_rows.filter(
                    start_node_id__in=new_node_ids, end_node_id__in=new_node_ids
                )
            else:
                rows = related_rows.filter(id__in=new_node_ids)
            content[list_key] = field.to_representation(rows)
        return content

    def _import_dependencies(
        self,
        export_data: dict,
        id_mapper: IDMapper,
        org_id: int | None = None,
        user=None,
        effective_permissions=None,
        created_venv_ids: list[int] | None = None,
    ) -> list[LastEditTrackedModel]:
        """Import all non-node, non-graph entity types in dependency order.

        Each new row needs CREATE on its ResourceType, gets the active org, and existing
        rows of that org are reused; denials are raised once, inside the caller's atomic
        block, so nothing persists. Returns the created rows that record their last edit.
        """
        dep_types = [
            et
            for et in DEPENDENCY_ORDER
            if et not in _NODE_ENTITY_TYPES and et != EntityType.GRAPH and et in export_data
        ]

        denied_resources = set()
        created_resources: list[LastEditTrackedModel] = []

        for entity_type in dep_types:
            if not self.registry.has_strategy(entity_type):
                logger.warning(
                    "Skipping unsupported entity type {} during partial import "
                    "(no longer supported)",
                    entity_type,
                )
                continue

            strategy = self.registry.get_strategy(entity_type)
            for entity_data in export_data.get(entity_type, []):
                old_id = entity_data["id"]
                existing = strategy.find_existing(entity_data, id_mapper, org_id=org_id)
                was_created = existing is None

                if was_created and effective_permissions is not None:
                    for created_type in (
                        entity_type,
                        *strategy.nested_entity_types(entity_data),
                    ):
                        resource = ENTITY_RESOURCE_MAP.get(created_type)
                        if resource is not None and not effective_permissions.can(
                            resource, Permission.CREATE
                        ):
                            denied_resources.add(resource)

                instance = strategy.import_entity(
                    entity_data,
                    id_mapper,
                    is_main=False,
                    org_id=org_id,
                    user=user,
                    created_venv_ids=created_venv_ids,
                )
                if instance is not None:
                    id_mapper.map(entity_type, old_id, instance.id, was_created)
                if was_created and isinstance(instance, LastEditTrackedModel):
                    created_resources.append(instance)

        if denied_resources:
            names = ", ".join(sorted(r.value for r in denied_resources))
            raise PermissionDenied(f"Missing CREATE permission on: {names}. No changes were made.")
        return created_resources

    def _collect_nodes(self, export_data: dict) -> list:
        """
        Gather node dicts from all node entity types and tag each with
        node_type so GraphStrategy._create_nodes can dispatch correctly.

        Partial files carry no version, so VersionConverter never sees them; a
        file written before node_number existed gets its "#N" badges moved here.
        """
        nodes = []
        for entity_type in _NODE_ENTITY_TYPES:
            for node_data in export_data.get(entity_type, []):
                node_copy = deepcopy(node_data)
                node_copy["node_type"] = entity_type
                move_legacy_badge_into_node_number(node_copy)
                nodes.append(node_copy)
        return nodes
