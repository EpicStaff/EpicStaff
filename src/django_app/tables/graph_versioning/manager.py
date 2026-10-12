from collections import defaultdict
from copy import deepcopy
from datetime import datetime

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from rbac.authorship import (
    RecordedLastEdit,
    record_last_edit,
    resolve_author,
    restore_last_edits,
)
from rbac.authorship.user_summary import USER_SUMMARY_FIELDS
from rbac.models import AuthorModel, LastEditTrackedModel, ResourceLastEdit

from tables.graph_versioning.constants import (
    _DEPENDENCY_ENTITY_TYPES,
    _DEPENDENCY_MODELS,
    _EXCLUDED_GRAPH_SCALARS,
)
from tables.graph_versioning.handlers import HANDLER_REGISTRY, _MissingSets
from tables.import_export.constants import NODE_MAPPING_KEY
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.strategies.graph import GraphStrategy
from tables.import_export.strategies.nodes.node_maps import (
    NODE_RELATIONS,
    NODE_TYPE_TO_ENTITY_TYPE,
)
from tables.import_export.version_conversions.base import VersionConverter
from tables.models import (
    ConditionalEdge,
    Graph,
    KeyValueNode,
    PythonCode,
    Secret,
    WebhookTrigger,
)
from tables.models.graph_models import StartNode, TelegramTriggerNode
from tables.services.copy_services.helpers import next_copy_name
from tables.services.key_value_table_service import KeyValueTableService
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
                    conditional_edges.append({"source_node_id": row.source_node_id, "names": names})
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
        """Re-link the declarations a snapshot recorded, warning about the rest.

        No secrets:USE check here — intentional, not a gap. Restoring a version (or
        creating a flow from one) only reproduces a secret binding that already
        existed in this org at some point; it never grants access to anything new.
        This is the third of three paths our secrets-permission guard deliberately
        leaves reachable without secrets:USE, per spec sec5 — see
        TestUngatedPathsStayUngated in
        tests/services_tests/test_secret_reference_coverage.py for the other two
        (copy_python_code, bulk-save node deletion) and the same rationale. Do not
        add a secrets:USE check here without revisiting that design decision first.
        """
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
    def _resolve_names(*, names: list[str], org_id: int) -> tuple[list[Secret], list[str]]:
        """Split recorded names into the Secrets that still exist and those gone.

        Scoped to one org, so a name that exists only in another organisation
        counts as missing rather than re-linking across the boundary.
        """
        rows = {
            secret.name: secret for secret in Secret.objects.filter(org_id=org_id, name__in=names)
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
                row = self._find_site_row(graph=graph, node_id=new_node_id, code_field=code_field)
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
                        node_name=getattr(row, "node_name", None) or f"node #{new_node_id}",
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
                            "the edge has no source node, so it cannot be identified after restore."
                        ),
                    )
                )
                continue

            new_source_id = node_mapper.get_or_none(NODE_MAPPING_KEY, int(old_source_id))
            if new_source_id is None:
                warnings.extend(
                    self._dropped(
                        names=names,
                        node_name=label,
                        reason_suffix=(
                            "its source node was not restored, so the edge cannot be identified."
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
                else TelegramTriggerNode.objects.filter(pk=new_node_id, graph=graph).first()
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

    def resolve_node_authorship(
        self, *, recorded_authorship: dict | None, recorded_last_edits: dict | None
    ) -> dict[str, dict]:
        """Return each recorded node's author and last edit, with users loaded in one query.

        Keyed by the snapshot's node ids: every node with a ``node_authorship`` or a
        ``node_last_edit`` entry. Users are instances carrying only the user-summary
        columns, ``None`` when none was recorded, it was cleared, or the user no longer
        exists; times are datetimes, ``None`` when not recorded. Empty for a snapshot
        saved before node authorship was recorded.
        """
        recorded_authorship = recorded_authorship or {}
        recorded_last_edits = recorded_last_edits or {}
        node_ids = recorded_authorship.keys() | recorded_last_edits.keys()
        recorded_by_node_id = {
            node_id: (recorded_authorship.get(node_id, {}), recorded_last_edits.get(node_id, {}))
            for node_id in node_ids
        }
        wanted_user_ids = {
            user_id
            for authorship, last_edit in recorded_by_node_id.values()
            for user_id in (authorship.get("created_by"), last_edit.get("edited_by"))
            if user_id is not None
        }
        users_by_id = (
            get_user_model().objects.only(*USER_SUMMARY_FIELDS).in_bulk(wanted_user_ids)
            if wanted_user_ids
            else {}
        )
        return {
            node_id: {
                "created_by": users_by_id.get(authorship.get("created_by")),
                "created_at": self._parse_recorded_time(authorship.get("created_at")),
                "last_edited_by": users_by_id.get(last_edit.get("edited_by")),
                "last_edited_at": self._parse_recorded_time(last_edit.get("edited_at")),
            }
            for node_id, (authorship, last_edit) in recorded_by_node_id.items()
        }

    @staticmethod
    def _parse_recorded_time(recorded_time: str | None) -> datetime | None:
        return datetime.fromisoformat(recorded_time) if recorded_time else None

    def collect_node_authorship(self, *, graph: Graph) -> dict[str, dict]:
        """Record each node's author id and ISO-8601 ``created_at``, keyed by node id."""
        authorship: dict[str, dict] = {}
        for node_model in self._author_tracked_node_models():
            rows = node_model.objects.filter(graph=graph).values_list(
                "id", "created_by_id", "created_at"
            )
            for node_id, author_id, created_at in rows:
                authorship[str(node_id)] = {
                    "created_by": author_id,
                    "created_at": created_at.isoformat(),
                }
        return authorship

    def restore_node_authorship(
        self, *, graph: Graph, recorded_authorship: dict | None, node_mapper: IDMapper
    ) -> None:
        """Replay each recreated node's recorded author and ``created_at`` verbatim.

        A restore replays recorded state and never makes the restoring user an author. A
        node recorded without an author, or with no ``node_authorship`` entry at all (e.g.
        a version saved before authorship was recorded), ends up without one; its
        ``created_at`` is then left as the recreation set it. Recorded authors are not
        checked against the organization's members: removing a member, revoking a
        superadmin or deleting a user clears them from the snapshots of every organization
        they no longer belong to (``VersionSnapshotAuthorshipScrubber``).
        """
        recreated_node_ids = node_mapper.get_new_ids(NODE_MAPPING_KEY)
        if not recreated_node_ids:
            return

        recorded_by_new_id = self._recorded_by_new_node_id(recorded_authorship, node_mapper)

        for node_model in self._author_tracked_node_models():
            # Through the model manager: the graph's related manager would load each
            # row's deferred graph_id with its own query.
            nodes = list(
                node_model.objects.filter(graph=graph, id__in=recreated_node_ids).only(
                    "id", "created_by", "created_at"
                )
            )
            if not nodes:
                continue
            for node in nodes:
                entry = recorded_by_new_id.get(node.id)
                if entry is None:
                    node.created_by_id = None
                    continue
                node.created_by_id = entry["created_by"]
                node.created_at = datetime.fromisoformat(entry["created_at"])
            # Restore replays recorded state, so bypassing AuthorModel.save()'s author-change
            # guard and created_at's auto_now_add is intended. Must run after every step that
            # saves recreated nodes: a later full save() of a stale instance would overwrite it.
            node_model.objects.bulk_update(nodes, ["created_by", "created_at"])

    def collect_node_last_edits(self, *, graph: Graph) -> dict[str, dict]:
        """Record each node's last editor id and ISO-8601 ``edited_at``, keyed by node id.

        Nodes that were never edited have no entry.
        """
        graph_nodes = Q()
        for node_model in self._last_edit_tracked_node_models():
            graph_nodes |= Q(
                content_type=ContentType.objects.get_for_model(node_model),
                object_id__in=node_model.objects.filter(graph=graph).values("id"),
            )
        rows = ResourceLastEdit.objects.filter(graph_nodes).values_list(
            "object_id", "edited_by_id", "edited_at"
        )
        return {
            str(node_id): {"edited_by": editor_id, "edited_at": edited_at.isoformat()}
            for node_id, editor_id, edited_at in rows
        }

    def restore_node_last_edits(
        self, *, graph: Graph, recorded_last_edits: dict | None, node_mapper: IDMapper
    ) -> None:
        """Replay each recreated node's recorded last edit verbatim.

        A recreated node without a recorded entry (never edited when the version was
        saved, or a version saved before last edits were recorded) ends up without a last
        edit, discarding the one its recreation recorded. Nodes that were not recreated
        are skipped. Recorded editors are not checked against the organization's members:
        removing a member, revoking a superadmin or deleting a user clears them from the
        snapshots of every organization they no longer belong to
        (``VersionSnapshotAuthorshipScrubber``).
        """
        recreated_node_ids = node_mapper.get_new_ids(NODE_MAPPING_KEY)
        if not recreated_node_ids:
            return

        recorded_by_new_id = self._recorded_by_new_node_id(recorded_last_edits, node_mapper)
        restored: list[RecordedLastEdit] = []
        never_edited_nodes = Q()
        for node_model in self._last_edit_tracked_node_models():
            nodes = node_model.objects.filter(graph=graph, id__in=recreated_node_ids).only("id")
            never_edited_ids = []
            for node in nodes:
                entry = recorded_by_new_id.get(node.id)
                if entry is None:
                    never_edited_ids.append(node.id)
                    continue
                restored.append(
                    RecordedLastEdit(
                        resource=node,
                        edited_by_id=entry["edited_by"],
                        edited_at=datetime.fromisoformat(entry["edited_at"]),
                    )
                )
            if never_edited_ids:
                never_edited_nodes |= Q(
                    content_type=ContentType.objects.get_for_model(node_model),
                    object_id__in=never_edited_ids,
                )
        if never_edited_nodes:
            ResourceLastEdit.objects.filter(never_edited_nodes).delete()
        restore_last_edits(restored)

    @staticmethod
    def _recorded_by_new_node_id(
        recorded_by_old_node_id: dict | None, node_mapper: IDMapper
    ) -> dict[int, dict]:
        """Re-key a snapshot's per-node entries by recreated node id, dropping unmapped nodes."""
        recorded_by_new_id: dict[int, dict] = {}
        for old_node_id, entry in (recorded_by_old_node_id or {}).items():
            new_node_id = node_mapper.get_or_none(NODE_MAPPING_KEY, int(old_node_id))
            if new_node_id is not None:
                recorded_by_new_id[new_node_id] = entry
        return recorded_by_new_id

    @staticmethod
    def _author_tracked_node_models() -> list[type[AuthorModel]]:
        node_models = (
            Graph._meta.get_field(relation_name).related_model
            for relation_name in NODE_RELATIONS.values()
        )
        return [node_model for node_model in node_models if issubclass(node_model, AuthorModel)]

    @staticmethod
    def _last_edit_tracked_node_models() -> list[type[LastEditTrackedModel]]:
        node_models = (
            Graph._meta.get_field(relation_name).related_model
            for relation_name in NODE_RELATIONS.values()
        )
        return [
            node_model for node_model in node_models if issubclass(node_model, LastEditTrackedModel)
        ]

    def collect_dependencies(self, graph: Graph) -> dict:
        """
        Build a lightweight manifest of external dependency IDs
        the graph currently references. No full serialization — just IDs.
        """
        raw_deps = self._graph_strategy.extract_dependencies_from_instance(graph)
        light_deps = {
            str(entity_type.value): list(ids) for entity_type, ids in raw_deps.items() if ids
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

            existing_ids = set(model.objects.filter(id__in=ids).values_list("id", flat=True))

            # set as missing webhook triggers without any tunnel config
            # (provider_type=None means no NgrokWebhookConfig or LocalhostWebhookConfig attached)
            if entity_type_value == EntityType.WEBHOOK_TRIGGER.value:
                unconfigured_ids = set(
                    WebhookTrigger.objects.filter(
                        id__in=existing_ids,
                        provider_type__isnull=True,
                    ).values_list("id", flat=True)
                )
                existing_ids -= unconfigured_ids

            available_deps[entity_type_value] = [i for i in ids if i in existing_ids]
            missing_deps[entity_type_value] = [i for i in ids if i not in existing_ids]

        return {"available": available_deps, "missing": missing_deps}

    def _build_missing_sets(self, missing: dict) -> _MissingSets:
        """Gather all missing dependencies ids into dataclass structure"""
        return _MissingSets(
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

            # Old snapshots still carry nodes of types that no longer exist.
            # Skipping feeds their ids into skipped_node_ids, so the cleanup
            # below drops the references pointing at them.
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
                            f"Node type '{node_type}' is no longer supported and was skipped."
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

    def bind_key_value_tables(
        self, snapshot_nodes: list[dict], org_id: int, user=None
    ) -> list[dict]:
        """Return ``snapshot_nodes`` with each Key-Value node's table re-bound inside ``org_id``.

        Uses the lookup a restore uses (``KeyValueTableService.resolve_reference``) without
        persisting, so ``key_value_table`` holds the live id of the table a restore by ``user``
        would bind, or ``None`` when that table was deleted or renamed and no table of
        ``org_id`` has the stored name, or ``user`` lacks the node mode's permissions on it.
        A table of another organization is never returned. ``key_value_table_name`` keeps
        the name stored in the snapshot.
        """
        key_value_table_service = KeyValueTableService()
        bound_nodes = []
        for node in snapshot_nodes:
            # One or two queries per Key-Value node, like restore.
            if node.get("node_type") == NodeType.KEY_VALUE_NODE:
                table = key_value_table_service.resolve_reference(
                    org_id,
                    node.get("key_value_table"),
                    node.get("key_value_table_name"),
                    mode=node.get("mode", KeyValueNode.Mode.READ),
                    user=user,
                )
                node = {**node, "key_value_table": table.id if table else None}
            bound_nodes.append(node)
        return bound_nodes

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
            self._clean_decision_table_refs(filtered_snapshot["nodes"], skipped_node_ids)
        )

        warnings.extend(self._clean_agent_task_node_refs(filtered_snapshot["nodes"], missing_sets))

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
        self, graph: Graph, filtered_snapshot: dict, available_deps: dict, user=None
    ) -> IDMapper:
        self._graph_strategy.wipe_graph_children(graph)
        self._update_graph_scalars(graph, filtered_snapshot)

        id_mapper = self._build_identity_id_mapper(available_deps)

        node_mapper = self._graph_strategy.recreate_graph_children(
            graph,
            filtered_snapshot,
            id_mapper,
            user=user,
        )

        return node_mapper

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
        user=None,
    ) -> tuple[Graph, IDMapper]:
        """
        Create a brand-new Graph from a filtered snapshot.
        The new graph is independent — no GraphVersion rows, own id/uuid.
        `user` authors the new graph and every node recreated in it, and is recorded
        as their last editor.
        """
        snapshot_copy = deepcopy(filtered_snapshot)

        # make sure no extremely long name allowed
        suggest_name = f"{graph_name} from {version_name}"
        new_graph_name = suggest_name[:80] + "..." if len(suggest_name) > 80 else suggest_name

        snapshot_copy["description"] = (
            f'Flow created from "{version_name}" version of "{graph_name}" flow'
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

        with transaction.atomic():
            snapshot_copy["name"] = next_copy_name(Graph, org_id=org_id, base_name=new_graph_name)

        serializer = self._graph_strategy.serializer_class(data=snapshot_copy)
        serializer.is_valid(raise_exception=True)
        graph = serializer.save(org_id=org_id, created_by=resolve_author(user))

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
            user=user,
        )
        record_last_edit(graph, user)

        return graph, node_mapper

    def change_old_warnings_ids(self, warning_msgs: list[dict], node_mapper: IDMapper) -> None:
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
