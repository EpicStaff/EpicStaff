from functools import lru_cache

from django.apps import apps
from django.db import connection, transaction
from rbac.authorship import LAST_EDIT_TRACKER_CONTEXT_KEY, LastEditTracker
from tables.exceptions import BulkSaveValidationError, GraphSaveVersionConflictError
from tables.models import Graph
from tables.models.base_models import BaseGlobalNode
from tables.models.graph_models import ConditionalEdge, Edge
from tables.serializers.graph_bulk_save_serializers import (
    ConditionalEdgeBulkSerializer,
    EdgeBulkSerializer,
)
from tables.services.graph_bulk_save_service.data_types import (
    BuildSaveableResult,
    EdgeListValidationResult,
    NodeListValidationResult,
    NodeRef,
    ParsedNodeRef,
)
from tables.services.graph_bulk_save_service.registry import (
    EDGE_DELETE_CONFIGS,
    NODE_TYPE_REGISTRY,
    NodeTypeConfig,
)
from tables.services.graph_bulk_save_service.saveables import (
    _ConditionalEdgeSaveable,
    _EdgeSaveable,
    _NodeSaveable,
)


class GraphBulkSaveService:
    """
    Two-pass bulk save:
        Pass 1  validate everything and collect saveables (no DB writes).
        Pass 2  execute deletions then saves atomically; nodes before edges
              so the temp_id -> real_id map is ready when edges are written.

    Raises BulkSaveValidationError with a structured error dict if any entity
    fails validation. No DB writes happen in that case.

    A node gets a last edit only when its own state changed (a move is not a node
    edit); the graph gets one when anything in it changed, moves included.
    """

    # The active request, set per-invocation in save(). Threaded into every
    # node/edge serializer's context so org-scoped fields can resolve the active
    # org. Defaults to None so a helper called without save() denies (fail-safe).
    _request = None
    # Shared by every node/edge serializer of one save(); None without a request,
    # because a save without an acting user records no last edit.
    _last_edit_tracker: LastEditTracker | None = None

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_global_node_models() -> tuple[type, ...]:
        """Return all concrete BaseGlobalNode subclasses. Cached for process lifetime."""
        return tuple(
            m for m in apps.get_models() if issubclass(m, BaseGlobalNode) and not m._meta.abstract
        )

    @transaction.atomic
    def save(self, graph: Graph, validated_input: dict, request=None) -> Graph:
        # Thread the request so node/edge serializers can org-scope their FK
        # fields (e.g. CrewNode.crew_id, SubGraphNode.subgraph). Without it those
        # fields deny all pks rather than falling back to an unfiltered queryset.
        self._request = request
        expected_save_version = validated_input["save_version"]
        deleted_data = validated_input.get("deleted", {})
        all_errors: dict = {}
        node_saveables: list[_NodeSaveable] = []
        edge_saveables: list = []
        self._serializer_context = {"request": self._request}
        self._last_edit_tracker = LastEditTracker(request.user) if request is not None else None
        if self._last_edit_tracker is not None:
            self._serializer_context[LAST_EDIT_TRACKER_CONTEXT_KEY] = self._last_edit_tracker

        payload_temp_ids: set[str] = self._collect_payload_temp_ids(validated_input)

        # Pass 1: validate saving version
        if graph.save_version != expected_save_version:
            raise GraphSaveVersionConflictError(current_version=graph.save_version)

        # Pass 1: validate deletions
        deletion_errors = self._validate_deletions(graph, deleted_data)
        if deletion_errors:
            all_errors["deleted"] = deletion_errors

        # Pass 1: validate nodes (driven by registry — no hardcoded lists)
        routing_refs_to_validate: set[int] = set()
        for config in NODE_TYPE_REGISTRY:
            incoming = validated_input.get(config.list_key, [])
            if not incoming:
                continue
            db_map = {obj.id: obj for obj in config.model_class.objects.filter(graph=graph)}
            result = self._validate_node_list(graph, incoming, config, db_map, payload_temp_ids)
            if result.errors:
                all_errors[config.list_key] = result.errors
            else:
                node_saveables.extend(result.node_saveables)
                edge_saveables.extend(result.deferred_saveables)
                routing_refs_to_validate |= result.real_routing_node_ids

        # Pass 1: validate edges
        existing_node_ref_errors = []
        edge_refs_to_validate: set[int] = set()

        edge_result = self._validate_edge_list(
            graph,
            validated_input.get("edge_list", []),
            EdgeBulkSerializer,
            Edge,
            payload_temp_ids,
        )
        if edge_result.errors:
            all_errors["edge_list"] = edge_result.errors
        else:
            edge_saveables.extend(edge_result.saveables)
            edge_refs_to_validate |= edge_result.real_node_ids

        cond_result = self._validate_conditional_edge_list(
            graph,
            validated_input.get("conditional_edge_list", []),
            payload_temp_ids,
        )
        if cond_result.errors:
            all_errors["conditional_edge_list"] = cond_result.errors
        else:
            edge_saveables.extend(cond_result.saveables)
            edge_refs_to_validate |= cond_result.real_node_ids

        # Batch-validate that every real (non-temp) node ref across edge types and
        # decision table routing fields belongs to this graph. The message is the
        # same for a nonexistent and a foreign id, so existence never leaks.
        all_real_refs = edge_refs_to_validate | routing_refs_to_validate
        if all_real_refs:
            invalid_ids = self._find_node_ids_outside_graph(all_real_refs, graph.id)
            if invalid_ids:
                # Partition errors by source for clearer attribution.
                invalid_edge_refs = invalid_ids & edge_refs_to_validate
                invalid_routing_refs = invalid_ids & routing_refs_to_validate
                if invalid_edge_refs:
                    existing_node_ref_errors.append(
                        f"Edge references node IDs not found in this graph: "
                        f"{sorted(invalid_edge_refs)}"
                    )
                if invalid_routing_refs:
                    existing_node_ref_errors.append(
                        f"Decision table routing references node IDs not found in this graph: "
                        f"{sorted(invalid_routing_refs)}"
                    )
        if existing_node_ref_errors:
            all_errors.setdefault("edge_list", []).extend(existing_node_ref_errors)

        if all_errors:
            raise BulkSaveValidationError(all_errors)

        # Pass 2: atomic write
        self._execute_writes(
            graph,
            deleted_data,
            node_saveables,
            edge_saveables,
            expected_save_version,
        )
        return graph

    def _validate_node_list(
        self,
        graph: Graph,
        incoming_list: list[dict],
        config: NodeTypeConfig,
        db_map: dict,
        payload_temp_ids: set[str],
    ) -> NodeListValidationResult:
        """Validate all items in one node list."""
        result = NodeListValidationResult()

        for index, item_data in enumerate(incoming_list):
            item_data = dict(item_data)
            # The URL graph is the authority: a per-item graph would let an item
            # be written into (or moved to) another graph that skips the checks below.
            item_data["graph"] = graph.id
            item_id = item_data.get("id")
            temp_id = str(item_data.pop("temp_id", None) or "")  # wire-only, strip now

            if item_id is None:
                item_data.pop("id", None)
                build = self._build_saveable(config, item_data, index, payload_temp_ids)
            else:
                db_instance = db_map.get(item_id)
                if db_instance is None:
                    result.errors.append(
                        {
                            "index": index,
                            "errors": f"id={item_id} not found in graph {graph.id}",
                        }
                    )
                    continue

                item_data.pop("id", None)
                build = self._build_saveable(
                    config, item_data, index, payload_temp_ids, instance=db_instance
                )

            if build.error:
                result.errors.append(build.error)
            else:
                result.node_saveables.append(_NodeSaveable(build.inner_saveable, temp_id or None))
                if build.deferred_saveable is not None:
                    result.deferred_saveables.append(build.deferred_saveable)
                    result.real_routing_node_ids |= self._collect_real_routing_refs(
                        build.deferred_saveable
                    )

        return result

    def _build_saveable(
        self,
        config: NodeTypeConfig,
        data: dict,
        index: int,
        payload_temp_ids: set[str],
        instance=None,
    ) -> BuildSaveableResult:
        """Build one saveable via the config factory."""
        data, extra = config.saveable_factory.preprocess_data(data, payload_temp_ids)

        # Surface routing validation errors collected by preprocess_data before
        # attempting serializer construction.
        routing_errors = extra.get("routing_errors", [])
        if routing_errors:
            return BuildSaveableResult(error={"index": index, "errors": routing_errors})

        s = (
            config.serializer_class(instance, data=data, context=self._serializer_context)
            if instance is not None
            else config.serializer_class(data=data, context=self._serializer_context)
        )
        if not s.is_valid():
            return BuildSaveableResult(error={"index": index, "errors": s.errors})

        inner = config.saveable_factory.build(s, extra, instance)
        deferred = config.saveable_factory.build_deferred(inner, extra)
        return BuildSaveableResult(inner_saveable=inner, deferred_saveable=deferred)

    @staticmethod
    def _collect_real_routing_refs(deferred) -> set[int]:
        """Extract real (non-temp) node IDs from a decision table or classification
        decision table refs saveable for the batch same-graph check in Pass 1."""
        refs: set[int] = set()
        for attr in ("_default_next_ref", "_next_error_ref"):
            ref = getattr(deferred, attr, None)
            if ref is not None and not ref.is_temp:
                refs.add(ref.value)
        for ref in getattr(deferred, "_group_refs", []):
            if ref is not None and not ref.is_temp:
                refs.add(ref.value)
        return refs

    def _validate_edge_list(
        self,
        graph: Graph,
        incoming_list: list[dict],
        serializer_class,
        model_class,
        payload_temp_ids: set[str],
    ) -> EdgeListValidationResult:
        """Validate all Edge items."""
        result = EdgeListValidationResult()

        db_map = {obj.id: obj for obj in model_class.objects.filter(graph=graph)}

        for index, item_data in enumerate(incoming_list):
            item_data = dict(item_data)
            item_data["graph"] = graph.id
            item_id = item_data.get("id")

            start_parsed = self._parse_node_ref(
                item_data, "start_node_id", "start_temp_id", payload_temp_ids, index
            )
            end_parsed = self._parse_node_ref(
                item_data, "end_node_id", "end_temp_id", payload_temp_ids, index
            )

            ref_errors = [p.error for p in (start_parsed, end_parsed) if p.error]
            if ref_errors:
                result.errors.extend(ref_errors)
                continue

            if start_parsed.ref and not start_parsed.ref.is_temp:
                result.real_node_ids.add(start_parsed.ref.value)
            if end_parsed.ref and not end_parsed.ref.is_temp:
                result.real_node_ids.add(end_parsed.ref.value)

            if item_id is None:
                item_data.pop("id", None)
                s = serializer_class(data=item_data, context=self._serializer_context)
                if not s.is_valid():
                    result.errors.append({"index": index, "errors": s.errors})
                    continue
                result.saveables.append(
                    _EdgeSaveable(s, start_parsed.ref, end_parsed.ref, instance=None)
                )
            else:
                db_instance = db_map.get(item_id)
                if db_instance is None:
                    result.errors.append(
                        {
                            "index": index,
                            "errors": f"id={item_id} not found in graph {graph.id}",
                        }
                    )
                    continue

                item_data.pop("id", None)
                s = serializer_class(db_instance, data=item_data, context=self._serializer_context)
                if not s.is_valid():
                    result.errors.append({"index": index, "errors": s.errors})
                    continue
                result.saveables.append(
                    _EdgeSaveable(s, start_parsed.ref, end_parsed.ref, instance=db_instance)
                )

        return result

    def _validate_conditional_edge_list(
        self,
        graph: Graph,
        incoming_list: list[dict],
        payload_temp_ids: set[str],
    ) -> EdgeListValidationResult:
        """Validate all ConditionalEdge items."""
        result = EdgeListValidationResult()

        db_map = {obj.id: obj for obj in ConditionalEdge.objects.filter(graph=graph)}

        for index, item_data in enumerate(incoming_list):
            item_data = dict(item_data)
            item_data["graph"] = graph.id
            item_id = item_data.get("id")

            source_parsed = self._parse_node_ref(
                item_data, "source_node_id", "source_temp_id", payload_temp_ids, index
            )
            if source_parsed.error:
                result.errors.append(source_parsed.error)
                continue

            if source_parsed.ref and not source_parsed.ref.is_temp:
                result.real_node_ids.add(source_parsed.ref.value)

            if item_id is None:
                item_data.pop("id", None)
                s = ConditionalEdgeBulkSerializer(data=item_data, context=self._serializer_context)
                if not s.is_valid():
                    result.errors.append({"index": index, "errors": s.errors})
                    continue
                result.saveables.append(
                    _ConditionalEdgeSaveable(s, source_parsed.ref, instance=None)
                )
            else:
                db_instance = db_map.get(item_id)
                if db_instance is None:
                    result.errors.append(
                        {
                            "index": index,
                            "errors": f"id={item_id} not found in graph {graph.id}",
                        }
                    )
                    continue

                item_data.pop("id", None)
                s = ConditionalEdgeBulkSerializer(
                    db_instance, data=item_data, context=self._serializer_context
                )
                if not s.is_valid():
                    result.errors.append({"index": index, "errors": s.errors})
                    continue
                result.saveables.append(
                    _ConditionalEdgeSaveable(s, source_parsed.ref, instance=db_instance)
                )

        return result

    @staticmethod
    def _parse_node_ref(
        item_data: dict,
        id_field: str,
        temp_field: str,
        payload_temp_ids: set[str],
        index: int,
    ) -> ParsedNodeRef:
        """Extract and validate one node ref from edge data."""
        node_id = item_data.get(id_field)
        temp_id = item_data.get(temp_field)

        has_id = node_id is not None
        has_temp = temp_id is not None

        if has_id and has_temp:
            return ParsedNodeRef(
                error={
                    "index": index,
                    "errors": f"Provide exactly one of {id_field} or {temp_field}, not both.",
                }
            )
        if not has_id and not has_temp:
            return ParsedNodeRef(
                error={
                    "index": index,
                    "errors": f"One of {id_field} or {temp_field} is required.",
                }
            )

        if has_temp:
            temp_str = str(temp_id)
            if temp_str not in payload_temp_ids:
                return ParsedNodeRef(
                    error={
                        "index": index,
                        "errors": (
                            f"{temp_field}={temp_str!r} does not match any temp_id "
                            f"in the node lists of this request."
                        ),
                    }
                )
            return ParsedNodeRef(ref=NodeRef(is_temp=True, value=temp_str))

        return ParsedNodeRef(ref=NodeRef(is_temp=False, value=node_id))

    def _validate_deletions(self, graph: Graph, deleted_data: dict) -> list[str]:
        """Verify all IDs in deleted dict belong to this graph. Returns error strings."""
        errors = []
        # edges first, then nodes — matches deletion order
        for config in [*EDGE_DELETE_CONFIGS, *NODE_TYPE_REGISTRY]:
            ids = deleted_data.get(config.delete_key) or []
            if not ids:
                continue
            found_ids = set(
                config.model_class.objects.filter(id__in=ids, graph=graph).values_list(
                    "id", flat=True
                )
            )
            invalid_ids = set(ids) - found_ids
            if invalid_ids:
                errors.append(
                    f"{config.delete_key}: IDs {sorted(invalid_ids)} not found in graph {graph.id}"
                )
        return errors

    @staticmethod
    def _collect_payload_temp_ids(validated_input: dict) -> set[str]:
        """Return all temp_id strings present in every node list. Derived from registry."""
        temp_ids: set[str] = set()
        for config in NODE_TYPE_REGISTRY:
            for item in validated_input.get(config.list_key, []):
                tid = item.get("temp_id")
                if tid is not None:
                    temp_ids.add(str(tid))
        return temp_ids

    @staticmethod
    def _find_node_ids_outside_graph(node_ids: set[int], graph_id: int) -> set[int]:
        """Return the subset of node_ids that are not an active BaseGlobalNode of graph_id.

        A nonexistent id, a soft-deleted node and an id belonging to another graph
        (or organization) all count as outside, so callers cannot tell them apart.
        Every concrete BaseGlobalNode model must have a ``graph`` FK and an
        ``is_soft_deleted`` field; ``get_field`` raises FieldDoesNotExist for one
        that does not, instead of silently skipping it.
        """
        if not node_ids:
            return set()

        node_models = GraphBulkSaveService._get_global_node_models()
        if not node_models:
            return node_ids

        id_list = list(node_ids)
        placeholders = ",".join(["%s"] * len(id_list))
        union_parts = [
            f"SELECT id FROM {m._meta.db_table} "
            f"WHERE {m._meta.get_field('graph').column} = %s "
            f"AND {m._meta.get_field('is_soft_deleted').column} = false "
            f"AND id IN ({placeholders})"
            for m in node_models
        ]
        query = " UNION ALL ".join(union_parts)
        params = [graph_id, *id_list] * len(node_models)

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            found_ids = {row[0] for row in cursor.fetchall()}

        return node_ids - found_ids

    def _execute_writes(
        self,
        graph: Graph,
        deleted_data: dict,
        node_saveables: list[_NodeSaveable],
        edge_saveables: list,
        expected_save_version: int,
    ):
        """Atomically delete, then save nodes, then save edges."""

        # check if graph was changed meanwhile editing
        Graph.increment_version_if_current(pk=graph.pk, expected=expected_save_version)

        temp_id_map: dict[str, int] = {}

        deleted_count = self._execute_deletions(graph, deleted_data)

        # Nodes first — populates temp_id_map for new nodes.
        for ns in node_saveables:
            ns.save(temp_id_map)

        # Edges second — temp refs resolved from the complete map.
        for es in edge_saveables:
            es.resolve_and_save(temp_id_map)

        self._record_last_edits(graph, deleted_count)

    def _execute_deletions(self, graph: Graph, deleted_data: dict) -> int:
        """Delete all requested entities in edges-before-nodes order; return the rows deleted."""
        deleted_count = 0
        for config in [*EDGE_DELETE_CONFIGS, *NODE_TYPE_REGISTRY]:
            ids = deleted_data.get(config.delete_key) or []
            if ids:
                deleted, _ = config.model_class.objects.filter(id__in=ids, graph=graph).delete()
                deleted_count += deleted
        return deleted_count

    def _record_last_edits(self, graph: Graph, deleted_count: int) -> None:
        # Runs after every node, edge and deferred routing write, so nested child
        # rows and routing refs are part of each node's comparison.
        if self._last_edit_tracker is None:
            return
        if deleted_count:
            self._last_edit_tracker.mark_edited(graph)
        self._last_edit_tracker.finish()
