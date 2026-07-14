import textwrap
from copy import deepcopy

from tables.import_export.enums import EntityType, NodeType
from tables.import_export.strategies.graph import GraphStrategy
from tables.import_export.id_mapper import IDMapper
from tables.import_export.version_conversions.base import VersionConverter
from tables.import_export.constants import NODE_MAPPING_KEY
from tables.import_export.utils import ensure_unique_identifier

from tables.graph_versioning.constants import (
    _EXCLUDED_GRAPH_SCALARS,
    _DEPENDENCY_ENTITY_TYPES,
    _DEPENDENCY_MODELS,
    _GRAPH_RELATION_NAMES,
)
from tables.graph_versioning.handlers import HANDLER_REGISTRY, _MissingSets
from tables.models import (
    Graph,
    ConditionalEdge,
    GraphOrganization,
    PythonCode,
    PythonCodeTool,
    PythonNode,
    WebhookTrigger,
    WebhookTriggerNode,
)


class GraphVersioningManager:
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

    def validate_dependencies(self, dependencies: dict) -> dict:
        """
        Split dependency IDs into available/missing buckets via bulk DB lookups,
        keyed by EntityType.value strings.
        """
        available_deps: dict[str, list[int]] = {}
        missing_deps: dict[str, list[int]] = {}

        for entity_type_value, ids in dependencies.items():
            model = _DEPENDENCY_MODELS.get(entity_type_value)

            ids = [i for i in ids if i is not None]

            if model is None or not ids:
                available_deps[entity_type_value] = []
                missing_deps[entity_type_value] = []
                continue

            existing_ids = set(
                model.objects.filter(id__in=ids).values_list("id", flat=True)
            )

            # set as missing webhook triggers without ngrok config
            if entity_type_value == EntityType.WEBHOOK_TRIGGER.value:
                unconfigured_ids = set(
                    WebhookTrigger.objects.filter(
                        id__in=existing_ids, ngrok_webhook_config__isnull=True
                    ).values_list("id", flat=True)
                )
                existing_ids -= unconfigured_ids

            available_deps[entity_type_value] = [i for i in ids if i in existing_ids]
            missing_deps[entity_type_value] = [i for i in ids if i not in existing_ids]

        return {"available": available_deps, "missing": missing_deps}

    def _build_missing_sets(self, missing: dict) -> _MissingSets:
        """Gather all missing dependencies ids into dataclass structure"""
        return _MissingSets(
            crews=set(missing.get(EntityType.CREW.value, [])),
            subgraphs=set(missing.get(EntityType.GRAPH.value, [])),
            llm_configs=set(missing.get(EntityType.LLM_CONFIG.value, [])),
            webhooks=set(missing.get(EntityType.WEBHOOK_TRIGGER.value, [])),
        )

    def _filter_nodes(
        self, nodes: list[dict], missing_sets: _MissingSets
    ) -> tuple[list[dict], set[int], list[dict]]:
        """Checks all graph nodes that rely on dependencies and skip them"""

        kept_nodes: list[dict] = []
        skipped_node_ids: set[int] = set()
        warnings: list[dict] = []

        for node in nodes:
            handler = HANDLER_REGISTRY.get(node.get("node_type"))
            if handler is not None:
                missing_id = handler.find_missing_id(node, missing_sets)
                if missing_id is not None:
                    should_skip, warning = handler.handle(node, missing_id)
                    warnings.append(warning)
                    if should_skip:
                        skipped_node_ids.add(node.get("id"))
                        continue
            kept_nodes.append(node)

        return kept_nodes, skipped_node_ids, warnings

    def _clean_decision_table_refs(
        self, snapshot_nodes: list[dict], skipped_node_ids: set[int]
    ) -> list[dict]:
        """
        Check DecisionTableNode connections.
        Set None if related entity doesn't exist
        """
        warnings: list[dict] = []

        for node in snapshot_nodes:
            if node.get("node_type") != NodeType.DECISION_TABLE_NODE:
                continue
            node_name = node.get("node_name") or NodeType.DECISION_TABLE_NODE
            for field in ("default_next_node_id", "next_error_node_id"):
                target = node.get(field)
                if target in skipped_node_ids:
                    node[field] = None
                    warnings.append(
                        {
                            "type": "decision_table_ref_cleared",
                            "node_name": node_name,
                            "field": field,
                            "missing_node_id": target,
                            "node_id": node.get("id"),
                            "reason": f"Referenced Node #{target} no longer exists.",
                        }
                    )

            for group in node.get("condition_groups", []) or []:
                target = group.get("next_node_id")
                if target in skipped_node_ids:
                    group["next_node_id"] = None
                    warnings.append(
                        {
                            "type": "decision_table_ref_cleared",
                            "node_name": node_name,
                            "field": f"condition_groups[{group.get('group_name')}].next_node_id",
                            "missing_node_id": target,
                            "node_id": node.get("id"),
                            "reason": f"Referenced Node #{target} no longer exists.",
                        }
                    )

        return warnings

    def _filter_edges(
        self, edges: list[dict], skipped_node_ids: set[int]
    ) -> tuple[list[dict], list[dict]]:
        """
        Filter all edges based on non existing nodes
        """

        kept_edges = []
        warnings = []

        for edge in edges:
            start = edge.get("start_node_id")
            end = edge.get("end_node_id")
            if start in skipped_node_ids or end in skipped_node_ids:
                warnings.append(
                    {
                        "type": "edge_dropped",
                        "reason": f"Edge {start}->{end} references a skipped node.",
                    }
                )
                continue
            kept_edges.append(edge)

        return kept_edges, warnings

    def _filter_conditional_edges(
        self, conditional_edges: list[dict], skipped_node_ids: set[int]
    ) -> tuple[list[dict], list[dict]]:
        """
        Filter conditional edges based on non existing nodes
        """
        kept_cond_edges = []
        warnings = []
        for edge in conditional_edges:
            source = edge.get("source_node_id")
            if source in skipped_node_ids:
                warnings.append(
                    {
                        "type": "edge_dropped",
                        "reason": f"Conditional edge from {source} references a skipped node.",
                    }
                )
                continue
            kept_cond_edges.append(edge)

        return kept_cond_edges, warnings

    def filter_snapshot(self, snapshot: dict, missing: dict) -> tuple[dict, list[dict]]:
        """
        Strip missing-dependency nodes, null orphaned FKs,
        and drop dangling edges, returning the pipeline-ready snapshot
        and warnings.
        """
        filtered_snapshot = deepcopy(snapshot)
        warnings: list[dict] = []

        missing_sets = self._build_missing_sets(missing)

        kept_nodes, skipped_node_ids, node_warnings = self._filter_nodes(
            filtered_snapshot.get("nodes", []), missing_sets
        )
        filtered_snapshot["nodes"] = kept_nodes
        warnings.extend(node_warnings)

        warnings.extend(
            self._clean_decision_table_refs(
                filtered_snapshot["nodes"], skipped_node_ids
            )
        )

        kept_edges, edge_warnings = self._filter_edges(
            filtered_snapshot.get("edge_list", []), skipped_node_ids
        )
        filtered_snapshot["edge_list"] = kept_edges
        warnings.extend(edge_warnings)

        kept_cond_edges, cond_warnings = self._filter_conditional_edges(
            filtered_snapshot.get("conditional_edge_list", []), skipped_node_ids
        )
        filtered_snapshot["conditional_edge_list"] = kept_cond_edges
        warnings.extend(cond_warnings)

        return filtered_snapshot, warnings

    def apply_snapshot_to_graph(
        self, graph: Graph, filtered_snapshot: dict, available_deps: dict
    ) -> IDMapper:
        self._wipe_graph_children(graph)
        self._update_graph_scalars(graph, filtered_snapshot)

        id_mapper = self._build_identity_id_mapper(available_deps)

        node_mapper = self._graph_strategy.recreate_graph_children(
            graph,
            filtered_snapshot,
            id_mapper,
        )

        return node_mapper

    def _wipe_graph_children(self, graph: Graph) -> None:
        """
        Wipe all graph related nodes
        """
        python_code_ids: set[int] = set()
        python_code_ids.update(
            PythonNode.objects.filter(graph=graph).values_list(
                "python_code_id", flat=True
            )
        )
        python_code_ids.update(
            ConditionalEdge.objects.filter(graph=graph).values_list(
                "python_code_id", flat=True
            )
        )
        python_code_ids.update(
            WebhookTriggerNode.objects.filter(graph=graph).values_list(
                "python_code_id", flat=True
            )
        )

        for relation_name in _GRAPH_RELATION_NAMES:
            getattr(graph, relation_name).all().delete()

        if python_code_ids:
            shared_ids = set(
                PythonCodeTool.objects.filter(
                    python_code_id__in=python_code_ids
                ).values_list("python_code_id", flat=True)
            )
            orphan_ids = python_code_ids - shared_ids
            if orphan_ids:
                PythonCode.objects.filter(id__in=orphan_ids).delete()

    def _update_graph_scalars(self, graph: Graph, snapshot: dict) -> None:
        """
        Updates graphs fields from version snapshot
        """
        update_fields = []
        graph_scalar_fields = [
            field.name
            for field in graph._meta.get_fields()
            if not field.is_relation and field.name not in _EXCLUDED_GRAPH_SCALARS
        ]
        for field in graph_scalar_fields:
            if field in snapshot:
                setattr(graph, field, snapshot[field])
                update_fields.append(field)
        if update_fields:
            graph.save(update_fields=update_fields)

    def _build_identity_id_mapper(self, available_deps: dict) -> IDMapper:
        id_mapper = IDMapper()
        for entity_type_value, ids in available_deps.items():
            entity_type = _DEPENDENCY_ENTITY_TYPES.get(entity_type_value)
            if entity_type is None:
                continue
            for entity_id in ids:
                id_mapper.map(entity_type, entity_id, entity_id, was_created=False)
        return id_mapper

    def convert_snapshot_to_current_version(self, snapshot: dict) -> dict:
        pseudo_bundle = {
            EntityType.GRAPH: [snapshot],
            "version": snapshot.get("version", 1),
            "main_entity": EntityType.GRAPH,
        }
        converted = VersionConverter.convert(pseudo_bundle)
        return converted[EntityType.GRAPH][0]

    def create_graph_from_snapshot(
        self,
        filtered_snapshot: dict,
        available_deps: dict,
        *,
        graph_name: str,
        version_name: str,
        org_id: int,
    ) -> tuple[Graph, IDMapper]:
        """
        Create a brand-new Graph from a filtered snapshot.
        The new graph is independent — no GraphVersion rows, own id/uuid.
        """
        snapshot_copy = deepcopy(filtered_snapshot)

        # make sure no extremely long name allowed
        suggest_name = f"{graph_name} from {version_name}"
        new_graph_name = (
            suggest_name[:80] + "..." if len(suggest_name) > 80 else suggest_name
        )

        snapshot_copy["description"] = (
            f'Flow created from "{version_name}" version of "{graph_name}" flow'
        )
        snapshot_copy["name"] = ensure_unique_identifier(
            base_name=new_graph_name,
            existing_names=list(Graph.objects.values_list("name", flat=True)),
        )

        snapshot_copy.pop("id", None)
        snapshot_copy.pop("uuid", None)

        id_mapper = self._build_identity_id_mapper(available_deps)

        snapshot_copy["metadata"] = self._graph_strategy.update_metadata(
            snapshot_copy.get("metadata") or {}, id_mapper
        )

        nodes_data = snapshot_copy.pop("nodes", [])
        edges_data = snapshot_copy.pop("edge_list", [])
        cond_edges_data = snapshot_copy.pop("conditional_edge_list", [])

        serializer = self._graph_strategy.serializer_class(data=snapshot_copy)
        serializer.is_valid(raise_exception=True)
        graph = serializer.save(org_id=org_id)

        GraphOrganization.objects.get_or_create(graph=graph, organization_id=org_id)

        node_mapper = self._graph_strategy.recreate_graph_children(
            graph,
            {
                "nodes": nodes_data,
                "edge_list": edges_data,
                "conditional_edge_list": cond_edges_data,
            },
            id_mapper,
        )

        return graph, node_mapper

    def change_old_warnings_ids(
        self, warning_msgs: list[dict], node_mapper: IDMapper
    ) -> None:
        for w in warning_msgs:
            old_id = w.get("node_id")
            if old_id:
                w["node_id"] = node_mapper.get(NODE_MAPPING_KEY, old_id)
