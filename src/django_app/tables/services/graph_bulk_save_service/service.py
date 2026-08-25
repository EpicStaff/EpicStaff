from functools import lru_cache

from django.apps import apps
from django.db import connection, transaction

from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from tables.models.base_models import BaseGlobalNode
from tables.models import Graph
from tables.models.graph_models import ConditionalEdge, Edge
from tables.models.rbac_models import Organization

from tables.serializers.graph_bulk_save_serializers import (
    ConditionalEdgeBulkSerializer,
    EdgeBulkSerializer,
)
from tables.exceptions import BulkSaveValidationError, GraphSaveVersionConflictError
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
from utils.logger import logger


class GraphBulkSaveService:
    """
    Two-pass bulk save:
        Pass 1  validate everything and collect saveables (no DB writes).
        Pass 2  execute deletions then saves atomically; nodes before edges
              so the temp_id -> real_id map is ready when edges are written.

    Raises BulkSaveValidationError with a structured error dict if any entity
    fails validation. No DB writes happen in that case.
    """

    # The active request, set per-invocation in save(). Threaded into every
    # node/edge serializer's context so org-scoped fields can resolve the active
    # org. Defaults to None so a helper called without save() denies (fail-safe).
    _request = None
    # Explicit org id, set per-invocation in save() for non-request write paths
    # (e.g. WS autosave flush) that source it from a trusted server-side value
    # (graph.org_id) rather than a request. Threaded into every node/edge
    # serializer's context alongside _request. Defaults to None (fail-safe).
    _org_id = None

    @staticmethod
    def _resolve_organization() -> Organization | None:
        """Resolve the default organization for serializer validation context.

        Serializers treat a missing "organization" key in context as
        permissive (skip org-scoped validation) — see TaskNodeSerializer.validate.
        Falling back to None here preserves that behavior instead of raising
        when the default organization has not been provisioned.
        """
        try:
            return Organization.objects.get(name=DEFAULT_ORGANIZATION_NAME)
        except Organization.DoesNotExist:
            return None

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_global_node_models() -> tuple[type, ...]:
        """Return all concrete BaseGlobalNode subclasses. Cached for process lifetime."""
        return tuple(
            m
            for m in apps.get_models()
            if issubclass(m, BaseGlobalNode) and not m._meta.abstract
        )

    @transaction.atomic
    def save(
        self,
        graph: Graph,
        validated_input: dict,
        request=None,
        org_id=None,
        preauthorized_fields=None,
    ) -> tuple["Graph", dict[str, int]]:
        # Thread the request (and/or an explicit org_id for non-request write
        # paths) so node/edge serializers can org-scope their FK fields (e.g.
        # CrewNode.crew_id, SubGraphNode.subgraph). Without either, those fields
        # deny all pks rather than falling back to an unfiltered queryset.
        self._request = request
        self._org_id = org_id
        expected_save_version = validated_input["save_version"]
        deleted_data = validated_input.get("deleted", {})
        all_errors: dict = {}
        node_saveables: list[_NodeSaveable] = []
        edge_saveables: list = []
        self._serializer_context = {
            "organization": self._resolve_organization(),
            "request": self._request,
            "org_id": self._org_id,
            "preauthorized_fields": preauthorized_fields,
        }

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
            # Exclude ids pending deletion so Pass 1 validation sees the state Pass 2 will produce.
            pending_delete_ids = set(deleted_data.get(config.delete_key) or [])
            db_map = {
                obj.id: obj
                for obj in config.model_class.objects.filter(graph=graph)
                if obj.id not in pending_delete_ids
            }
            result = self._validate_node_list(
                graph, incoming, config, db_map, payload_temp_ids
            )
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

        # Batch-validate all real (non-temp) node refs across edge types and
        # decision table routing fields combined.
        all_real_refs = edge_refs_to_validate | routing_refs_to_validate
        if all_real_refs:
            invalid_ids = self._find_nonexistent_global_node_ids(all_real_refs)
            if invalid_ids:
                # Partition errors by source for clearer attribution.
                invalid_edge_refs = invalid_ids & edge_refs_to_validate
                invalid_routing_refs = invalid_ids & routing_refs_to_validate
                if invalid_edge_refs:
                    existing_node_ref_errors.append(
                        f"Edge references node IDs that do not exist: {sorted(invalid_edge_refs)}"
                    )
                if invalid_routing_refs:
                    existing_node_ref_errors.append(
                        f"DecisionTableNode routing references node IDs that do not exist: "
                        f"{sorted(invalid_routing_refs)}"
                    )
        if existing_node_ref_errors:
            all_errors.setdefault("edge_list", []).extend(existing_node_ref_errors)

        if all_errors:
            raise BulkSaveValidationError(all_errors)

        # Pass 2: atomic write
        temp_id_map = self._execute_writes(
            graph,
            deleted_data,
            node_saveables,
            edge_saveables,
            expected_save_version,
        )
        return graph, temp_id_map

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
        singleton_create_seen = False

        for index, item_data in enumerate(incoming_list):
            item_data = dict(item_data)
            item_id = item_data.get("id")
            temp_id = str(item_data.pop("temp_id", None) or "")  # wire-only, strip now

            if item_id is None:
                if config.is_singleton and (db_map or singleton_create_seen):
                    result.errors.append(
                        {
                            "index": index,
                            "errors": f"Only one {config.list_key} entry allowed per graph",
                        }
                    )
                    continue
                if config.is_singleton:
                    singleton_create_seen = True
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
                result.node_saveables.append(
                    _NodeSaveable(build.inner_saveable, temp_id or None)
                )
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
            config.serializer_class(
                instance, data=data, context=self._serializer_context
            )
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
        """Extract real (non-temp) node IDs from a _DecisionTableNodeRefsSaveable
        for batch existence validation in Pass 1."""
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
        existing_endpoint_pairs = set(
            model_class.objects.filter(graph=graph).values_list(
                "start_node_id", "end_node_id"
            )
        )
        payload_endpoint_pairs_seen: set[tuple[int, int]] = set()

        for index, item_data in enumerate(incoming_list):
            item_data = dict(item_data)
            item_id = item_data.get("id")
            temp_id = str(item_data.pop("temp_id", None) or "")  # wire-only, strip now

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
                is_resolved_pair = (
                    start_parsed.ref
                    and end_parsed.ref
                    and not start_parsed.ref.is_temp
                    and not end_parsed.ref.is_temp
                )
                if is_resolved_pair:
                    endpoint_pair = (start_parsed.ref.value, end_parsed.ref.value)
                    if (
                        endpoint_pair in existing_endpoint_pairs
                        or endpoint_pair in payload_endpoint_pairs_seen
                    ):
                        result.errors.append(
                            {
                                "index": index,
                                "errors": (
                                    f"An edge between nodes {endpoint_pair[0]} and "
                                    f"{endpoint_pair[1]} already exists in this graph"
                                ),
                            }
                        )
                        continue
                    payload_endpoint_pairs_seen.add(endpoint_pair)

                item_data.pop("id", None)
                s = serializer_class(data=item_data, context=self._serializer_context)
                if not s.is_valid():
                    result.errors.append({"index": index, "errors": s.errors})
                    continue
                result.saveables.append(
                    _EdgeSaveable(
                        s,
                        start_parsed.ref,
                        end_parsed.ref,
                        instance=None,
                        temp_id=temp_id or None,
                    )
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
                s = serializer_class(
                    db_instance, data=item_data, context=self._serializer_context
                )
                if not s.is_valid():
                    result.errors.append({"index": index, "errors": s.errors})
                    continue
                result.saveables.append(
                    _EdgeSaveable(
                        s,
                        start_parsed.ref,
                        end_parsed.ref,
                        instance=db_instance,
                        temp_id=temp_id or None,
                    )
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
        existing_source_ids = set(
            ConditionalEdge.objects.filter(graph=graph).values_list(
                "source_node_id", flat=True
            )
        )
        payload_source_ids_seen: set[int] = set()

        for index, item_data in enumerate(incoming_list):
            item_data = dict(item_data)
            item_id = item_data.get("id")
            temp_id = str(item_data.pop("temp_id", None) or "")  # wire-only, strip now

            source_parsed = self._parse_node_ref(
                item_data, "source_node_id", "source_temp_id", payload_temp_ids, index
            )
            if source_parsed.error:
                result.errors.append(source_parsed.error)
                continue

            if source_parsed.ref and not source_parsed.ref.is_temp:
                result.real_node_ids.add(source_parsed.ref.value)

            if item_id is None:
                is_resolved_source = source_parsed.ref and not source_parsed.ref.is_temp
                if is_resolved_source:
                    source_id = source_parsed.ref.value
                    if (
                        source_id in existing_source_ids
                        or source_id in payload_source_ids_seen
                    ):
                        result.errors.append(
                            {
                                "index": index,
                                "errors": (
                                    f"A conditional edge from node {source_id} "
                                    "already exists in this graph"
                                ),
                            }
                        )
                        continue
                    payload_source_ids_seen.add(source_id)

                item_data.pop("id", None)
                s = ConditionalEdgeBulkSerializer(
                    data=item_data, context=self._serializer_context
                )
                if not s.is_valid():
                    result.errors.append({"index": index, "errors": s.errors})
                    continue
                result.saveables.append(
                    _ConditionalEdgeSaveable(
                        s, source_parsed.ref, instance=None, temp_id=temp_id or None
                    )
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
                    _ConditionalEdgeSaveable(
                        s,
                        source_parsed.ref,
                        instance=db_instance,
                        temp_id=temp_id or None,
                    )
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
        """Check deletion ids in ``deleted_data`` against the DB. Never raises."""
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
                logger.debug(
                    "{}: IDs {} already absent from graph {} — deletion intent "
                    "already satisfied, skipping",
                    config.delete_key,
                    sorted(invalid_ids),
                    graph.id,
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
    def _find_nonexistent_global_node_ids(node_ids: set[int]) -> set[int]:
        """Return the subset of node_ids that do not exist in any BaseGlobalNode table."""
        if not node_ids:
            return set()

        node_models = GraphBulkSaveService._get_global_node_models()
        if not node_models:
            return node_ids

        id_list = list(node_ids)
        placeholders = ",".join(["%s"] * len(id_list))
        union_parts = [
            f"SELECT id FROM {m._meta.db_table} WHERE id IN ({placeholders})"
            for m in node_models
        ]
        query = " UNION ALL ".join(union_parts)
        params = id_list * len(node_models)

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
    ) -> dict[str, int]:
        """Atomically delete, then save nodes, then save edges.

        Returns the temp_id_map built during writes: maps each frontend temp uuid
        string to the new DB integer id assigned on insert. Covers node temp_ids
        (registered by _NodeSaveable) as well as edge and conditional-edge temp_ids
        (registered by _EdgeSaveable / _ConditionalEdgeSaveable), all in one flat map.
        """

        # check if graph was changed meanwhile editing
        Graph.increment_version_if_current(pk=graph.pk, expected=expected_save_version)

        temp_id_map: dict[str, int] = {}

        self._execute_deletions(graph, deleted_data)

        # Nodes first — populates temp_id_map for new nodes.
        for ns in node_saveables:
            ns.save(temp_id_map)

        # Edges second — temp refs resolved from the complete map.
        for es in edge_saveables:
            es.resolve_and_save(temp_id_map)

        return temp_id_map

    def _execute_deletions(self, graph: Graph, deleted_data: dict):
        """Delete all requested entities in edges-before-nodes order."""
        for config in [*EDGE_DELETE_CONFIGS, *NODE_TYPE_REGISTRY]:
            ids = deleted_data.get(config.delete_key) or []
            if ids:
                config.model_class.objects.filter(id__in=ids, graph=graph).delete()
