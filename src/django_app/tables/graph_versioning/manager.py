import textwrap
from collections import defaultdict
from copy import deepcopy

from tables.graph_versioning.constants import (
    _DEPENDENCY_ENTITY_TYPES,
    _DEPENDENCY_MODELS,
    _EXCLUDED_GRAPH_SCALARS,
    _GRAPH_RELATION_NAMES,
)
from tables.graph_versioning.handlers import HANDLER_REGISTRY, _MissingSets
from tables.import_export.constants import NODE_MAPPING_KEY
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.strategies.graph import GraphStrategy
from tables.import_export.strategies.nodes.node_maps import NODE_TYPE_TO_ENTITY_TYPE
from tables.import_export.utils import ensure_unique_identifier
from tables.import_export.version_conversions.base import VersionConverter
from tables.models import (
    ConditionalEdge,
    Graph,
    PythonCode,
    PythonCodeTool,
    PythonNode,
    Secret,
    WebhookTrigger,
    WebhookTriggerNode,
)
from tables.models.graph_models import StartNode, TelegramTriggerNode
from tables.services.persistent_variables_service import (
    PersistentVariablesService,
)
from tables.services.secrets.python_code_sites import GRAPH_PYTHON_CODE_SITES


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

    def collect_secret_declarations(self, *, graph: Graph) -> dict:
        """Which secret names each of this graph's Python-code sites declares."""
        nodes: dict[str, dict[str, list[str]]] = {}
        conditional_edges: list[dict] = []

        for site in GRAPH_PYTHON_CODE_SITES:
            rows = (
                site.model.objects.filter(graph=graph)
                .select_related(site.code_field)
                .prefetch_related(f"{site.code_field}__secrets")
            )
            for row in rows:
                python_code = getattr(row, site.code_field)
                if python_code is None:
                    continue
                names = sorted(secret.name for secret in python_code.secrets.all())
                if not names:
                    continue
                if site.model is ConditionalEdge:
                    conditional_edges.append(
                        {"source_node_id": row.source_node_id, "names": names}
                    )
                else:
                    nodes.setdefault(str(row.pk), {})[site.code_field] = names

        return {
            "nodes": nodes,
            "conditional_edges": conditional_edges,
            "telegram": self._collect_telegram_secrets(graph=graph),
        }

    def restore_secret_declarations(
        self, *, graph: Graph, declarations: dict | None, node_mapper: IDMapper
    ) -> list[dict]:
        """Re-link the declarations a snapshot recorded, warning about the rest."""
        if not declarations:
            return []

        warnings: list[dict] = []
        warnings.extend(
            self._restore_node_declarations(
                graph=graph,
                recorded=declarations.get("nodes") or {},
                node_mapper=node_mapper,
            )
        )
        warnings.extend(
            self._restore_conditional_edge_declarations(
                graph=graph,
                recorded=declarations.get("conditional_edges") or [],
                node_mapper=node_mapper,
            )
        )
        warnings.extend(
            self._restore_telegram_declarations(
                graph=graph,
                recorded=declarations.get("telegram") or {},
                node_mapper=node_mapper,
            )
        )
        return warnings

    @staticmethod
    def _resolve_names(
        *, names: list[str], org_id: int
    ) -> tuple[list[Secret], list[str]]:
        """Split recorded names into the Secrets that still exist and those gone.

        Scoped to one org, so a name that exists only in another organisation
        counts as missing rather than re-linking across the boundary.
        """
        rows = {
            secret.name: secret
            for secret in Secret.objects.filter(org_id=org_id, name__in=names)
        }
        resolved = [rows[name] for name in names if name in rows]
        missing = [name for name in names if name not in rows]
        return resolved, missing

    def _restore_node_declarations(
        self, *, graph: Graph, recorded: dict, node_mapper: IDMapper
    ) -> list[dict]:
        warnings: list[dict] = []
        for old_node_id, by_code_field in recorded.items():
            new_node_id = node_mapper.get_or_none(NODE_MAPPING_KEY, int(old_node_id))
            for code_field, names in by_code_field.items():
                if new_node_id is None:
                    warnings.extend(
                        self._dropped(
                            names=names,
                            node_name=f"node #{old_node_id}",
                            reason_suffix=(
                                "its node was not restored, so the declaration "
                                "had nowhere to attach."
                            ),
                        )
                    )
                    continue
                row = self._find_site_row(
                    graph=graph, node_id=new_node_id, code_field=code_field
                )
                if row is None:
                    warnings.extend(
                        self._dropped(
                            names=names,
                            node_name=f"node #{new_node_id}",
                            reason_suffix=(
                                f"no restored node carries a '{code_field}' to "
                                "attach the declaration to."
                            ),
                        )
                    )
                    continue
                warnings.extend(
                    self._link(
                        python_code=getattr(row, code_field),
                        names=names,
                        org_id=graph.org_id,
                        node_name=getattr(row, "node_name", None)
                        or f"node #{new_node_id}",
                    )
                )
        return warnings

    @staticmethod
    def _find_site_row(*, graph: Graph, node_id: int, code_field: str):
        """The restored row for one (node id, code field) pair."""
        for site in GRAPH_PYTHON_CODE_SITES:
            if site.model is ConditionalEdge or site.code_field != code_field:
                continue
            row = (
                site.model.objects.filter(pk=node_id, graph=graph)
                .select_related(code_field)
                .first()
            )
            if row is not None:
                return row
        return None

    def _restore_conditional_edge_declarations(
        self, *, graph: Graph, recorded: list, node_mapper: IDMapper
    ) -> list[dict]:
        """Correlate edge declarations through the node each edge branches off."""
        warnings: list[dict] = []
        by_source: dict[object, list[dict]] = defaultdict(list)
        for entry in recorded:
            by_source[entry.get("source_node_id")].append(entry)

        for old_source_id, entries in by_source.items():
            names = sorted({name for entry in entries for name in entry["names"]})
            label = f"conditional edge from node #{old_source_id}"

            if old_source_id is None:
                warnings.extend(
                    self._dropped(
                        names=names,
                        node_name=label,
                        reason_suffix=(
                            "the edge has no source node, so it cannot be "
                            "identified after restore."
                        ),
                    )
                )
                continue

            new_source_id = node_mapper.get_or_none(
                NODE_MAPPING_KEY, int(old_source_id)
            )
            if new_source_id is None:
                warnings.extend(
                    self._dropped(
                        names=names,
                        node_name=label,
                        reason_suffix=(
                            "its source node was not restored, so the edge "
                            "cannot be identified."
                        ),
                    )
                )
                continue

            edges = list(
                ConditionalEdge.objects.filter(
                    graph=graph, source_node_id=new_source_id
                ).select_related("python_code")
            )
            if len(edges) != 1 or len(entries) != 1:
                warnings.extend(
                    self._dropped(
                        names=names,
                        node_name=label,
                        reason_suffix=(
                            f"{len(entries)} recorded declaration(s) and "
                            f"{len(edges)} restored edge(s) share that source "
                            "node, so the pairing is ambiguous."
                        ),
                    )
                )
                continue

            warnings.extend(
                self._link(
                    python_code=edges[0].python_code,
                    names=names,
                    org_id=graph.org_id,
                    node_name=label,
                )
            )
        return warnings

    def _restore_telegram_declarations(
        self, *, graph: Graph, recorded: dict, node_mapper: IDMapper
    ) -> list[dict]:
        warnings: list[dict] = []
        for old_node_id, name in recorded.items():
            new_node_id = node_mapper.get_or_none(NODE_MAPPING_KEY, int(old_node_id))
            node = (
                None
                if new_node_id is None
                else TelegramTriggerNode.objects.filter(
                    pk=new_node_id, graph=graph
                ).first()
            )
            if node is None:
                warnings.extend(
                    self._dropped(
                        names=[name],
                        node_name=f"node #{old_node_id}",
                        reason_suffix="its node was not restored.",
                    )
                )
                continue

            resolved, missing = self._resolve_names(names=[name], org_id=graph.org_id)
            if missing:
                warnings.extend(
                    self._dropped(
                        names=missing,
                        node_name=node.node_name,
                        reason_suffix=(
                            "it no longer exists in this organization, so the "
                            "bot token was not restored."
                        ),
                    )
                )
                continue
            node.telegram_bot_api_key_secret = resolved[0]
            node.save(update_fields=["telegram_bot_api_key_secret"])
        return warnings

    def _link(
        self, *, python_code: PythonCode, names: list[str], org_id: int, node_name: str
    ) -> list[dict]:
        """Attach every name that still resolves; warn about every one that does not."""
        resolved, missing = self._resolve_names(names=names, org_id=org_id)
        python_code.secrets.set(resolved)
        return self._dropped(
            names=missing,
            node_name=node_name,
            reason_suffix="it no longer exists in this organization.",
        )

    @staticmethod
    def _dropped(*, names: list[str], node_name: str, reason_suffix: str) -> list[dict]:
        """One warning per lost declaration, shaped like the dependency warnings.

        Same keys the restore response already carries, so the caller renders these
        with no change on its side.
        """
        return [
            {
                "type": "secret_declaration_dropped",
                "node_name": node_name,
                "reason": (
                    f'Secret "{name}" was declared when this version was saved, '
                    f"but {reason_suffix} The declaration was not restored."
                ),
            }
            for name in names
        ]

    @staticmethod
    def _collect_telegram_secrets(graph: Graph) -> dict[str, str]:
        """TelegramTriggerNode's bot-token secret, by name."""
        rows = TelegramTriggerNode.objects.filter(
            graph=graph, telegram_bot_api_key_secret__isnull=False
        ).select_related("telegram_bot_api_key_secret")
        return {str(row.pk): row.telegram_bot_api_key_secret.name for row in rows}

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
            agent_definitions=set(missing.get(EntityType.AGENT_DEFINITION.value, [])),
            surfaces=set(missing.get(EntityType.SURFACE.value, [])),
            python_code_tools=set(missing.get(EntityType.PYTHON_CODE_TOOL.value, [])),
            mcp_tools=set(missing.get(EntityType.MCP_TOOL.value, [])),
        )

    def _filter_nodes(
        self, nodes: list[dict], missing_sets: _MissingSets
    ) -> tuple[list[dict], set[int], list[dict]]:
        """Checks all graph nodes that rely on dependencies and skip them"""

        kept_nodes: list[dict] = []
        skipped_node_ids: set[int] = set()
        warnings: list[dict] = []

        for node in nodes:
            node_type = node.get("node_type")

            # Snapshots taken before a node type was removed still carry its nodes
            # (e.g. CodeAgentNode after EST-3813). Skipping them here feeds their ids
            # into skipped_node_ids, so the decision-table / edge / conditional-edge
            # cleanup below drops the references too, instead of the restore blowing
            # up later on KeyError or a dangling edge.
            if node_type not in NODE_TYPE_TO_ENTITY_TYPE:
                skipped_node_ids.add(node.get("id"))
                # No "node_id": the node is never recreated, so change_old_warnings_ids
                # would have nothing to remap it to — same contract as node_skipped.
                warnings.append(
                    {
                        "type": "node_type_unsupported",
                        "node_name": node.get("node_name") or node_type,
                        "node_type": node_type,
                        "reason": (
                            f"Node type '{node_type}' is no longer supported "
                            "and was skipped."
                        ),
                    }
                )
                continue

            handler = HANDLER_REGISTRY.get(node_type)
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
        Check DecisionTableNode and ClassificationDecisionTableNode connections.
        Set None if related entity doesn't exist.

        Both node types carry the same reference shape (default_next_node_id,
        next_error_node_id and condition_groups[].next_node_id). CDT references are
        also blanked later by _remap_classification_decision_table_references, but
        only clearing them here puts them in the restore warnings, so the user is
        told which branches were dropped.
        """
        table_node_types = (
            NodeType.DECISION_TABLE_NODE,
            NodeType.CLASSIFICATION_DECISION_TABLE_NODE,
        )
        warnings: list[dict] = []

        for node in snapshot_nodes:
            node_type = node.get("node_type")
            if node_type not in table_node_types:
                continue
            node_name = node.get("node_name") or node_type
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

    def _clean_agent_task_node_refs(
        self, snapshot_nodes: list[dict], missing_sets: _MissingSets
    ) -> list[dict]:
        """
        Check AgentNode/TaskNode surface_list and inline_surface tool refs.
        Drop ids referencing deleted Surfaces/PythonCodeTools/MCPTools.
        """
        warnings: list[dict] = []

        for node in snapshot_nodes:
            if node.get("node_type") not in (NodeType.AGENT_NODE, NodeType.TASK_NODE):
                continue

            warnings.extend(self._clean_node_surface_list(node, missing_sets.surfaces))
            warnings.extend(self._clean_node_inline_surface_tools(node, missing_sets))

        return warnings

    def _clean_node_surface_list(self, node: dict, missing_surfaces: set) -> list[dict]:
        node_name = node.get("node_name") or node.get("node_type")
        surface_ids = node.get("surface_list") or []
        kept_surface_ids = []
        warnings: list[dict] = []

        for surface_id in surface_ids:
            if surface_id not in missing_surfaces:
                kept_surface_ids.append(surface_id)
                continue
            warnings.append(
                {
                    "type": "surface_dropped",
                    "node_name": node_name,
                    "node_type": node.get("node_type"),
                    "node_id": node.get("id"),
                    "missing_id": surface_id,
                    "reason": f"Referenced Surface #{surface_id} no longer exists.",
                }
            )

        node["surface_list"] = kept_surface_ids
        return warnings

    def _clean_node_inline_surface_tools(
        self, node: dict, missing_sets: _MissingSets
    ) -> list[dict]:
        inline_surface = node.get("inline_surface")
        if not inline_surface:
            return []

        tools = inline_surface.get("tools") or {}
        warnings: list[dict] = []

        warnings.extend(
            self._clean_inline_tool_entries(
                node,
                tools,
                tool_key=EntityType.PYTHON_CODE_TOOL.value,
                id_field="python_tool_id",
                missing_ids=missing_sets.python_code_tools,
                tool_label="Python tool",
            )
        )
        warnings.extend(
            self._clean_inline_tool_entries(
                node,
                tools,
                tool_key=EntityType.MCP_TOOL.value,
                id_field="mcp_tool_id",
                missing_ids=missing_sets.mcp_tools,
                tool_label="MCP tool",
            )
        )

        return warnings

    def _clean_inline_tool_entries(
        self,
        node: dict,
        tools: dict,
        *,
        tool_key: str,
        id_field: str,
        missing_ids: set,
        tool_label: str,
    ) -> list[dict]:
        node_name = node.get("node_name") or node.get("node_type")
        entries = tools.get(tool_key) or []
        kept_entries = []
        warnings: list[dict] = []

        for entry in entries:
            tool_id = entry.get(id_field)
            if tool_id not in missing_ids:
                kept_entries.append(entry)
                continue
            warnings.append(
                {
                    "type": "inline_tool_dropped",
                    "node_name": node_name,
                    "node_type": node.get("node_type"),
                    "node_id": node.get("id"),
                    "missing_id": tool_id,
                    "reason": f"Referenced {tool_label} #{tool_id} no longer exists.",
                }
            )

        tools[tool_key] = kept_entries
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

        warnings.extend(
            self._clean_agent_task_node_refs(filtered_snapshot["nodes"], missing_sets)
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

        start_node = StartNode.objects.filter(graph=graph).first()
        PersistentVariablesService().seed_for_copy(
            graph, start_node.variables if start_node else {}
        )

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
            if not old_id:
                continue
            new_id = node_mapper.get_or_none(NODE_MAPPING_KEY, old_id)
            if new_id is None:
                # The node was not recreated, so no current id exists. Drop the key
                # rather than leave the snapshot id behind — it would point at an
                # unrelated node in the restored graph. Raising here would turn a
                # successful restore into a 500 over a cosmetic field.
                w.pop("node_id", None)
                continue
            w["node_id"] = new_id
