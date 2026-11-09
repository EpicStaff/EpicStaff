"""What each kind of export job exports, who may start it, and what its archive holds.

Every export runs as a background job that produces a `.zip` (`TransferJobRunner`).
One `ExportJobDefinition` per `TransferJob.MainEntity` says how the job is checked,
scoped, named and written. Adding an exportable entity:

1. Add its value to `TransferJob.MainEntity` (and a migration for the choices).
2. Add an `ExportJobDefinition` here (an `EnvelopeExportDefinition` when the
   archive is the plain `export.json` envelope) and register it in
   `EXPORT_JOB_DEFINITIONS`.
3. Give its viewset `ExportJobActionMixin` with `export_job_definition` and, when
   the `export-jobs` body holds more than `ids`, `export_job_request_serializer_class`
   (whose validated data `build_request` reads). Map `export_jobs` to the
   definition's `permission` in its `rbac_action_map`.

This module is serializer-free: request bodies are validated by the viewset, and
a definition only reads their validated data.
"""

import io
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from django.db.models import Model, Q, QuerySet
from rbac.models.enums import Permission, ResourceType
from tables.import_export.archive import ExportArchiveWriter
from tables.import_export.enums import EntityType
from tables.import_export.export_exclusions import ExcludedEntity
from tables.import_export.export_format_strategies import (
    ArchiveExportFormatStrategy,
    CsvExportFormatStrategy,
    write_json_envelope,
)
from tables.import_export.export_tabular_projections.export_classification_decision_table_csv import (
    export_condition_groups_csv,
)
from tables.import_export.export_tabular_projections.session import SessionTabularProjection
from tables.import_export.permissions import ENTITY_RESOURCE_MAP, ExportAccessPolicy
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.partial_export_service import (
    LIST_KEY_TO_ENTITY_TYPE,
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.session_export_reader import ExportedSessions, iter_session_entries
from tables.models import (
    AuditFilterPreset,
    ClassificationDecisionTableNode,
    Graph,
    McpTool,
    PythonCodeTool,
    Session,
    SourceCollection,
    TransferJob,
)
from tables.models.user import User
from tables.utils.helpers import generate_file_name

SESSIONS_JSON_MEMBER = "sessions.json"
SESSIONS_CSV_MEMBER = "sessions.csv"


class TransferJobError(Exception):
    """A failure the job's creator may be told about, as `{code, message}`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class TransferLane(StrEnum):
    """Which consumer runs a job: heavy jobs never hold up light ones."""

    HEAVY = "heavy"
    LIGHT = "light"


@dataclass(frozen=True)
class ExportArtifact:
    """An export written to a temporary zip that the caller owns and deletes."""

    path: str
    # The name the download is called by, before its prefix and date.
    base_name: str
    excluded: list[ExcludedEntity] = field(default_factory=list)


class ExportJobDefinition(ABC):
    """How one main entity is exported as a job.

    A job's request always holds `ids`: the items `scoped_queryset` must find, all
    of them, both when the job is started and again when it runs.
    """

    main_entity: TransferJob.MainEntity
    # Start of the archive's file name, e.g. `flow` in `flow_support_2026-01-01.zip`.
    file_prefix: str
    # The right a caller needs, on `resource_type`, to start the job and to download it.
    resource_type: ResourceType
    permission: Permission = Permission.EXPORT
    lane: TransferLane = TransferLane.LIGHT
    # How the job list names a job of several items: "3 <plural_label>".
    plural_label: str

    @abstractmethod
    def scoped_queryset(self, *, user: User, org_id: int) -> QuerySet:
        """Every item of this entity `user` may export from `org_id`."""

    def build_request(self, validated_data: dict) -> dict:
        """The job's stored request, from the validated body of its `export-jobs` action."""
        return {"ids": list(validated_data["ids"])}

    def display_name(self, selected: QuerySet, request: dict) -> str:
        """The name the job list shows: the item's own name, or how many items there are.

        Args:
            selected: The requested items, already checked to all be found.
        """
        count = len(request["ids"])
        if count == 1:
            return self.item_name(selected.get())
        return f"{count} {self.plural_label}"

    @abstractmethod
    def item_name(self, instance) -> str:
        """The name of one exported item."""

    @abstractmethod
    def write_archive(
        self, job: TransferJob, selected: QuerySet, *, user: User, org_id: int
    ) -> ExportArtifact:
        """Write the job's archive into a temporary zip.

        Args:
            selected: The requested items, already checked to all be found.

        Raises:
            TransferJobError: Something requested can no longer be exported.
        """

    def base_name(self, selected: QuerySet, request: dict) -> str:
        count = len(request["ids"])
        return self.item_name(selected.get()) if count == 1 else f"bulk_{count}"


class EnvelopeExportDefinition(ExportJobDefinition):
    """An export whose archive holds the `export.json` envelope (and any collection files).

    The archive imports again as it is: through an import job for flows and
    collections, through the synchronous `import/` of the others.
    """

    def __init__(
        self,
        *,
        entity_type: EntityType,
        model: type[Model],
        file_prefix: str,
        plural_label: str,
        scope: Callable[[User, int], Q],
        lane: TransferLane = TransferLane.LIGHT,
        resource_type: ResourceType | None = None,
        permission: Permission = Permission.EXPORT,
        carries_knowledge_flag: bool = False,
    ):
        self.entity_type = entity_type
        self._model = model
        self.main_entity = TransferJob.MainEntity(entity_type.value)
        self.file_prefix = file_prefix
        self.plural_label = plural_label
        self._scope = scope
        self.lane = lane
        self.resource_type = resource_type or ENTITY_RESOURCE_MAP[entity_type]
        self.permission = permission
        self._carries_knowledge_flag = carries_knowledge_flag

    def scoped_queryset(self, *, user: User, org_id: int) -> QuerySet:
        return self._model.objects.filter(self._scope(user, org_id))

    def build_request(self, validated_data: dict) -> dict:
        request = super().build_request(validated_data)
        if self._carries_knowledge_flag:
            request["include_knowledge"] = validated_data["include_knowledge"]
        return request

    def item_name(self, instance) -> str:
        strategy = entity_registry.get_strategy(self.entity_type)
        return str(strategy.get_preview_data(instance)["name"])

    def write_archive(
        self, job: TransferJob, selected: QuerySet, *, user: User, org_id: int
    ) -> ExportArtifact:
        result = ExportService(entity_registry).export_entities(
            self.entity_type,
            list(job.request["ids"]),
            org_id=org_id,
            policy=ExportAccessPolicy.for_user(user, org_id),
            include_knowledge=job.request.get("include_knowledge", False),
        )
        return ExportArtifact(
            path=ArchiveExportFormatStrategy().render_to_file(result),
            base_name=self.base_name(selected, job.request),
            excluded=result.excluded,
        )


class SessionExportDefinition(ExportJobDefinition):
    """Sessions with their messages, as `sessions.json` or `sessions.csv`; never imported."""

    main_entity = TransferJob.MainEntity.SESSION
    file_prefix = "session"
    resource_type = ResourceType.FLOWS
    # One job may carry thousands of sessions with every message.
    lane = TransferLane.HEAVY
    plural_label = "sessions"

    def scoped_queryset(self, *, user: User, org_id: int) -> QuerySet:
        return Session.objects.visible_in_org(org_id)

    def build_request(self, validated_data: dict) -> dict:
        return {
            "ids": list(validated_data["ids"]),
            "export_format": validated_data["export_format"],
        }

    def display_name(self, selected: QuerySet, request: dict) -> str:
        # Never loads a session row: a session carries its flow's whole schema.
        ids = request["ids"]
        return f"Session {ids[0]}" if len(ids) == 1 else f"{len(ids)} {self.plural_label}"

    def item_name(self, instance) -> str:
        return f"Session {instance.pk}"

    def base_name(self, selected: QuerySet, request: dict) -> str:
        ids = request["ids"]
        return str(ids[0]) if len(ids) == 1 else f"bulk_{len(ids)}"

    def write_archive(
        self, job: TransferJob, selected: QuerySet, *, user: User, org_id: int
    ) -> ExportArtifact:
        # Written one session at a time: a job of thousands of sessions with all their
        # messages must not be held in the memory the web workers share. Nothing is
        # ever excluded: a session's only dependencies are its own sub-sessions.
        sessions = ExportedSessions.collect(selected, job.request["ids"])
        with ExportArchiveWriter() as writer:
            if job.request["export_format"] == "csv":
                projection = SessionTabularProjection()
                rows = projection.expand_in_session_order(
                    iter_session_entries(sessions.ids_by_session_id), sessions.tree_of
                )
                with (
                    writer.open_member(SESSIONS_CSV_MEMBER) as member,
                    io.TextIOWrapper(member, encoding="utf-8", newline="") as stream,
                ):
                    CsvExportFormatStrategy(projection).write_rows(rows, stream)
            else:
                with (
                    writer.open_member(SESSIONS_JSON_MEMBER) as member,
                    io.TextIOWrapper(member, encoding="utf-8", newline="") as stream,
                ):
                    write_json_envelope(
                        EntityType.SESSION,
                        iter_session_entries(sessions.depth_first_ids),
                        stream,
                    )
        return ExportArtifact(path=writer.path, base_name=self.base_name(selected, job.request))


class ClassificationDecisionTableExportDefinition(ExportJobDefinition):
    """One classification decision table node, as partial-export JSON or a readable CSV.

    The JSON is `export.json` holding what a partial export of the node holds, so
    the archive imports into a flow through `partial-import`.
    """

    main_entity = TransferJob.MainEntity.CLASSIFICATION_DECISION_TABLE_NODE
    file_prefix = "CDT"
    resource_type = ResourceType.FLOWS
    plural_label = "decision tables"

    def scoped_queryset(self, *, user: User, org_id: int) -> QuerySet:
        return ClassificationDecisionTableNode.objects.filter(graph__org_id=org_id)

    def build_request(self, validated_data: dict) -> dict:
        return {
            "ids": list(validated_data["ids"]),
            "export_format": validated_data["export_format"],
        }

    def item_name(self, instance) -> str:
        return instance.node_name

    def write_archive(
        self, job: TransferJob, selected: QuerySet, *, user: User, org_id: int
    ) -> ExportArtifact:
        if job.request["export_format"] == "csv":
            node = selected.select_related("default_llm_config__model").get()
            csv_name = generate_file_name(node.node_name, prefix=self.file_prefix)
            with ExportArchiveWriter() as writer:
                writer.add_bytes(
                    csv_name.removesuffix(".json") + ".csv",
                    export_condition_groups_csv(node).getvalue().encode(),
                )
            return ExportArtifact(path=writer.path, base_name=node.node_name)

        node = selected.get()
        result = GraphPartialExportService(entity_registry).export(
            [NodeRef(entity_type=EntityType.CLASSIFICATION_DECISION_TABLE_NODE, node_id=node.pk)],
            org_id=org_id,
            policy=ExportAccessPolicy.for_user(user, org_id),
        )
        if result.has_errors:
            raise TransferJobError("not_found", _partial_export_errors(result.errors))
        with ExportArchiveWriter() as writer:
            writer.write_envelope(result.data)
        return ExportArtifact(path=writer.path, base_name=node.node_name, excluded=result.excluded)


class FlowNodesExportDefinition(ExportJobDefinition):
    """Nodes picked in the flow editor with their dependencies, as `export.json`.

    The archive imports into a flow through `partial-import`. The job's `ids` hold
    the one flow the nodes belong to; the node and edge ids are checked when it runs.
    """

    main_entity = TransferJob.MainEntity.FLOW_NODES
    file_prefix = "graph_nodes"
    resource_type = ResourceType.FLOWS
    plural_label = "flows"

    def scoped_queryset(self, *, user: User, org_id: int) -> QuerySet:
        return Graph.objects.filter(org_id=org_id)

    def build_request(self, validated_data: dict) -> dict:
        return {
            "ids": list(validated_data["ids"]),
            "nodes": {
                list_key: list(validated_data[list_key])
                for list_key in LIST_KEY_TO_ENTITY_TYPE
                if validated_data.get(list_key)
            },
            "edge_list": list(validated_data.get("edge_list", [])),
        }

    def display_name(self, selected: QuerySet, request: dict) -> str:
        node_count = sum(len(node_ids) for node_ids in request["nodes"].values())
        noun = "node" if node_count == 1 else "nodes"
        return f"{node_count} {noun} from {selected.get().name}"

    def item_name(self, instance) -> str:
        return instance.name

    def base_name(self, selected: QuerySet, request: dict) -> str:
        return f"nodes_{selected.get().name}"

    def write_archive(
        self, job: TransferJob, selected: QuerySet, *, user: User, org_id: int
    ) -> ExportArtifact:
        node_refs = [
            NodeRef(entity_type=LIST_KEY_TO_ENTITY_TYPE[list_key], node_id=node_id)
            for list_key, node_ids in job.request["nodes"].items()
            for node_id in node_ids
        ]
        result = GraphPartialExportService(entity_registry).export(
            node_refs,
            org_id=org_id,
            edge_ids=job.request["edge_list"],
            policy=ExportAccessPolicy.for_user(user, org_id),
        )
        if result.has_errors:
            raise TransferJobError("not_found", _partial_export_errors(result.errors))
        with ExportArchiveWriter() as writer:
            writer.write_envelope(result.data)
        return ExportArtifact(
            path=writer.path,
            base_name=self.base_name(selected, job.request),
            excluded=result.excluded,
        )


def _partial_export_errors(errors: list[dict]) -> str:
    # Each error names only an id the creator sent, never a row of another org.
    return " ".join(error["error"] for error in errors)


def _in_org(user: User, org_id: int) -> Q:
    return Q(org_id=org_id)


def _python_tool_scope(user: User, org_id: int) -> Q:
    # Built-in tools belong to no organization and every one may export them.
    return Q(built_in=True) | Q(org_id=org_id)


def _audit_preset_scope(user: User, org_id: int) -> Q:
    # A colleague's private preset is not the caller's to see, let alone export.
    return Q(org_id=org_id) & (Q(is_shared=True) | Q(created_by=user))


EXPORT_JOB_DEFINITIONS: dict[str, ExportJobDefinition] = {
    definition.main_entity: definition
    for definition in (
        EnvelopeExportDefinition(
            entity_type=EntityType.GRAPH,
            model=Graph,
            file_prefix="flow",
            plural_label="flows",
            scope=_in_org,
            lane=TransferLane.HEAVY,
            carries_knowledge_flag=True,
        ),
        EnvelopeExportDefinition(
            entity_type=EntityType.SOURCE_COLLECTION,
            model=SourceCollection,
            file_prefix="knowledge",
            plural_label="knowledge collections",
            scope=_in_org,
            lane=TransferLane.HEAVY,
        ),
        EnvelopeExportDefinition(
            entity_type=EntityType.PYTHON_CODE_TOOL,
            model=PythonCodeTool,
            file_prefix="python_code_tool",
            plural_label="tools",
            scope=_python_tool_scope,
        ),
        EnvelopeExportDefinition(
            entity_type=EntityType.MCP_TOOL,
            model=McpTool,
            file_prefix="mcp_tool",
            plural_label="MCP tools",
            scope=_in_org,
        ),
        # Presets are a convenience over audit browsing: every action on them,
        # export included, needs AUDIT read and nothing more.
        EnvelopeExportDefinition(
            entity_type=EntityType.AUDIT_FILTER_PRESET,
            model=AuditFilterPreset,
            file_prefix="audit_filter_preset",
            plural_label="audit filter presets",
            scope=_audit_preset_scope,
            resource_type=ResourceType.AUDIT,
            permission=Permission.READ,
        ),
        SessionExportDefinition(),
        ClassificationDecisionTableExportDefinition(),
        FlowNodesExportDefinition(),
    )
}


def export_definition(main_entity: str) -> ExportJobDefinition:
    """The definition of exports of `main_entity` (a `TransferJob.MainEntity` value)."""
    return EXPORT_JOB_DEFINITIONS[main_entity]
