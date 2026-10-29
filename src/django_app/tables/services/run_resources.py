"""What a run uses: every row it reaches from the row it starts from.

`RUN_REFERENCES` and `RUN_SECRET_MARKERS` are the walk; no other code decides what a run
touches. A `FollowField` row follows a forward FK, O2O or auto-through M2M by id, whatever the
target's recycle-bin state, because a run would use the target or fail on it. A
`FollowChildren` row follows the live rows of a child model (its default manager) whose FK
points at a reached row, as a run reads them. A `FollowSecretMarkers` row follows the
`epicstaff_secret(<name>)` markers of a header field by name, to the secret a run resolves for
it. The walk is deliberately broad: an agent counts with both LLM configs, all its default
surfaces and its voice configs, a collection with every RAG's embedder and LLM, and an
attached folder with every file under it. Over-counting shows in what a suspension stops;
a missed reference would let a run use something it should not.

Adding a reference (a new node type, a new FK on a model the walk reaches, a new child row):
add a `FollowField` or `FollowChildren` row, or an entry in `RUN_REFERENCE_EXEMPTIONS` or
`RUN_TRAVERSAL_STOPS` with the reason it is not followed. A new header field a run resolves
markers in (a field whose name ends in `extra_headers`) gets a `FollowSecretMarkers` row.
`tests/plugins_tests/test_run_resource_collector_coverage.py` fails until one is added.
"""

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache, reduce
from operator import or_
from types import MappingProxyType

from django.apps import apps
from django.db.models import Q
from tables.services.run_admission import RunKind, RunSubject
from tables.services.secrets.secret_resolver import extract_secret_marker_names


@dataclass(frozen=True, order=True)
class ResourceRef:
    """One row: `model_label` is `Model._meta.label`, for example "tables.Graph"."""

    model_label: str
    pk: int


@dataclass(frozen=True)
class RunResources:
    """What one run uses.

    Attributes:
        refs: Every row the walk reached, the start row included.
        storage_prefixes: Org-relative paths, ending in "/", of the storage folders the
            walk reached. Every file under one of them counts as used.
        secret_marker_names: Every name the `epicstaff_secret(<name>)` markers of the reached
            rows name, whether a secret has the name or not. The secrets a run resolves them
            to are in `refs`.
    """

    refs: frozenset[ResourceRef]
    storage_prefixes: frozenset[str]
    secret_marker_names: frozenset[str] = frozenset()

    def pks_of(self, model_label: str) -> frozenset[int]:
        """Return the ids of the reached rows of `model_label`."""
        return frozenset(ref.pk for ref in self.refs if ref.model_label == model_label)


@dataclass(frozen=True)
class FollowField:
    """Follow a forward FK, O2O or auto-through M2M `field` of `model`."""

    model: str
    field: str


@dataclass(frozen=True)
class FollowChildren:
    """Follow the live rows of `child` whose FK or O2O `fk` points at a reached row."""

    child: str
    fk: str


@dataclass(frozen=True)
class FollowSecretMarkers:
    """Follow the `epicstaff_secret(<name>)` markers in the header field `field` of `model`.

    A marker binds by name when a run starts, not by id when it is written: the run sends the
    live secret of that name in its organization (`SecretResolver.resolve_named`). So a marker
    reaches that secret, looked up in the organization of the row holding the marker; a name no
    live secret has reaches nothing, as the run would fail on it.
    """

    model: str
    field: str


RUN_REFERENCES: tuple[FollowField | FollowChildren, ...] = (
    # Every node type of a flow, even one without references, so a reference added to it
    # later is caught by the coverage test. Subflows enter through SubGraphNode.subgraph.
    FollowChildren("tables.PythonNode", "graph"),
    FollowChildren("tables.KnowledgeNode", "graph"),
    FollowChildren("tables.KeyValueNode", "graph"),
    FollowChildren("tables.SubGraphNode", "graph"),
    FollowChildren("tables.WebhookTriggerNode", "graph"),
    FollowChildren("tables.TelegramTriggerNode", "graph"),
    FollowChildren("tables.ClassificationDecisionTableNode", "graph"),
    FollowChildren("tables.TaskNode", "graph"),
    FollowChildren("tables.AgentNode", "graph"),
    FollowChildren("tables.GraphStorageFile", "graph"),
    FollowChildren("tables.FileExtractorNode", "graph"),
    FollowChildren("tables.AudioTranscriptionNode", "graph"),
    FollowChildren("tables.EndNode", "graph"),
    FollowChildren("tables.StartNode", "graph"),
    FollowChildren("tables.Edge", "graph"),
    FollowChildren("tables.DecisionTableNode", "graph"),
    FollowChildren("tables.ScheduleTriggerNode", "graph"),
    # Nodes.
    FollowField("tables.SubGraphNode", "subgraph"),
    FollowField("tables.PythonNode", "python_code"),
    FollowField("tables.WebhookTriggerNode", "python_code"),
    FollowField("tables.WebhookTriggerNode", "webhook_trigger"),
    FollowField("tables.TelegramTriggerNode", "webhook_trigger"),
    FollowField("tables.TelegramTriggerNode", "telegram_bot_api_key_secret"),
    FollowChildren("tables.TelegramTriggerNodeField", "telegram_trigger_node"),
    FollowField("tables.KnowledgeNode", "source_collection"),
    FollowChildren("tables.KnowledgeNodeNaiveRagSearchConfig", "knowledge_node"),
    FollowChildren("tables.KnowledgeNodeGraphRagBasicSearchConfig", "knowledge_node"),
    FollowChildren("tables.KnowledgeNodeGraphRagLocalSearchConfig", "knowledge_node"),
    FollowChildren("tables.KnowledgeNodeGraphRagGlobalSearchConfig", "knowledge_node"),
    FollowChildren("tables.KnowledgeNodeGraphRagDriftSearchConfig", "knowledge_node"),
    FollowField("tables.KeyValueNode", "key_value_table"),
    FollowField("tables.ClassificationDecisionTableNode", "default_llm_config"),
    FollowField("tables.ClassificationDecisionTableNode", "pre_python_code"),
    FollowField("tables.ClassificationDecisionTableNode", "post_python_code"),
    FollowChildren("tables.ClassificationDecisionTablePrompt", "cdt_node"),
    FollowField("tables.ClassificationDecisionTablePrompt", "llm_config"),
    FollowChildren("tables.ClassificationConditionGroup", "classification_decision_table_node"),
    FollowChildren(
        "tables.ClassificationConditionGroupSection", "classification_decision_table_node"
    ),
    FollowChildren("tables.ConditionGroup", "decision_table_node"),
    FollowChildren("tables.Condition", "condition_group"),
    FollowField("tables.TaskNode", "agent_definition"),
    FollowField("tables.TaskNode", "surface_list"),
    FollowChildren("agents.InlineSurface", "task_node"),
    FollowField("tables.AgentNode", "agent_definition"),
    FollowField("tables.AgentNode", "surface_list"),
    FollowChildren("agents.AgentInlineSurface", "agent_node"),
    FollowChildren("tables.AgentNodeTask", "agent_node"),
    FollowField("tables.GraphStorageFile", "storage_file"),
    # Surfaces: every item, whatever its allow or deny mode.
    FollowChildren("agents.SurfacePythonTool", "surface"),
    FollowField("agents.SurfacePythonTool", "python_tool"),
    FollowChildren("agents.SurfaceMcpTool", "surface"),
    FollowField("agents.SurfaceMcpTool", "mcp_tool"),
    FollowChildren("agents.SurfaceKnowledge", "surface"),
    FollowField("agents.SurfaceKnowledge", "collection"),
    FollowChildren("agents.SurfaceStorageItem", "surface"),
    FollowField("agents.SurfaceStorageItem", "storage_file"),
    FollowChildren("agents.InlineSurfacePythonTool", "inline_surface"),
    FollowField("agents.InlineSurfacePythonTool", "python_tool"),
    FollowChildren("agents.InlineSurfaceMcpTool", "inline_surface"),
    FollowField("agents.InlineSurfaceMcpTool", "mcp_tool"),
    FollowChildren("agents.InlineSurfaceKnowledge", "inline_surface"),
    FollowField("agents.InlineSurfaceKnowledge", "collection"),
    FollowChildren("agents.InlineSurfaceStorageItem", "inline_surface"),
    FollowField("agents.InlineSurfaceStorageItem", "storage_file"),
    FollowChildren("agents.AgentInlineSurfacePythonTool", "agent_inline_surface"),
    FollowField("agents.AgentInlineSurfacePythonTool", "python_tool"),
    FollowChildren("agents.AgentInlineSurfaceMcpTool", "agent_inline_surface"),
    FollowField("agents.AgentInlineSurfaceMcpTool", "mcp_tool"),
    FollowChildren("agents.AgentInlineSurfaceKnowledge", "agent_inline_surface"),
    FollowField("agents.AgentInlineSurfaceKnowledge", "collection"),
    FollowChildren("agents.AgentInlineSurfaceStorageItem", "agent_inline_surface"),
    FollowField("agents.AgentInlineSurfaceStorageItem", "storage_file"),
    FollowChildren("agents.SurfaceNaiveSearchConfig", "surface_knowledge"),
    FollowChildren("agents.SurfaceGraphBasicSearchConfig", "surface_knowledge"),
    FollowChildren("agents.SurfaceGraphLocalSearchConfig", "surface_knowledge"),
    FollowChildren("agents.SurfaceGraphGlobalSearchConfig", "surface_knowledge"),
    FollowChildren("agents.SurfaceGraphDriftSearchConfig", "surface_knowledge"),
    FollowChildren("agents.InlineSurfaceNaiveSearchConfig", "surface_knowledge"),
    FollowChildren("agents.InlineSurfaceGraphBasicSearchConfig", "surface_knowledge"),
    FollowChildren("agents.InlineSurfaceGraphLocalSearchConfig", "surface_knowledge"),
    FollowChildren("agents.InlineSurfaceGraphGlobalSearchConfig", "surface_knowledge"),
    FollowChildren("agents.InlineSurfaceGraphDriftSearchConfig", "surface_knowledge"),
    FollowChildren("agents.AgentInlineSurfaceNaiveSearchConfig", "surface_knowledge"),
    FollowChildren("agents.AgentInlineSurfaceGraphBasicSearchConfig", "surface_knowledge"),
    FollowChildren("agents.AgentInlineSurfaceGraphLocalSearchConfig", "surface_knowledge"),
    FollowChildren("agents.AgentInlineSurfaceGraphGlobalSearchConfig", "surface_knowledge"),
    FollowChildren("agents.AgentInlineSurfaceGraphDriftSearchConfig", "surface_knowledge"),
    # Agents: an agent counts with everything it references, for every place it runs.
    FollowField("agents.AgentDefinition", "llm_config"),
    FollowField("agents.AgentDefinition", "fcm_llm_config"),
    FollowChildren("agents.AgentDefaultSurface", "agent_definition"),
    FollowField("agents.AgentDefaultSurface", "surface"),
    FollowChildren("agents.Surface", "owner_agent"),
    FollowChildren("tables.RealtimeAgentDefinition", "agent_definition"),
    FollowField("tables.RealtimeAgentDefinition", "agent_definition"),
    FollowField("tables.RealtimeAgentDefinition", "openai_config"),
    FollowField("tables.RealtimeAgentDefinition", "elevenlabs_config"),
    FollowField("tables.RealtimeAgentDefinition", "gemini_config"),
    FollowField("tables.OpenAIRealtimeConfig", "api_key_secret"),
    FollowField("tables.OpenAIRealtimeConfig", "transcription_api_key_secret"),
    FollowField("tables.ElevenLabsRealtimeConfig", "api_key_secret"),
    FollowField("tables.GeminiRealtimeConfig", "api_key_secret"),
    # Tools and code.
    FollowField("tables.PythonCodeTool", "python_code"),
    FollowField("tables.PythonCode", "secrets"),
    FollowField("tables.McpTool", "auth_secret"),
    # Knowledge: every RAG of a collection, not only the one a node picks.
    FollowChildren("tables.BaseRagType", "source_collection"),
    FollowChildren("tables.NaiveRag", "base_rag_type"),
    FollowField("tables.NaiveRag", "embedder"),
    FollowChildren("tables.GraphRag", "base_rag_type"),
    FollowField("tables.GraphRag", "embedder"),
    FollowField("tables.GraphRag", "llm"),
    # Model configs.
    FollowField("tables.LLMConfig", "model"),
    FollowField("tables.LLMConfig", "api_key_secret"),
    FollowField("tables.EmbeddingConfig", "model"),
    FollowField("tables.EmbeddingConfig", "api_key_secret"),
    # Webhooks.
    FollowChildren("tables.WebhookTriggerAuth", "trigger"),
    FollowField("tables.WebhookTriggerAuth", "secret"),
    FollowChildren("tables.NgrokWebhookConfig", "trigger"),
    FollowField("tables.NgrokWebhookConfig", "auth_token_secret"),
    FollowChildren("tables.LocalhostWebhookConfig", "trigger"),
    # Voice channels.
    FollowField("tables.RealtimeChannel", "realtime_agent_definition"),
    FollowChildren("tables.TwilioChannel", "channel"),
    FollowField("tables.TwilioChannel", "auth_token_secret"),
    FollowField("tables.TwilioChannel", "webhook_trigger"),
)

# Every header field whose markers a run resolves (`SecretResolver` fills each payload field
# whose name ends in `extra_headers` from these).
RUN_SECRET_MARKERS: tuple[FollowSecretMarkers, ...] = (
    FollowSecretMarkers("tables.LLMConfig", "extra_headers"),
    FollowSecretMarkers("tables.EmbeddingConfig", "extra_headers"),
)

# Forward references of a model the walk reaches that it does not follow: (model, field).
RUN_REFERENCE_EXEMPTIONS: Mapping[tuple[str, str], str] = MappingProxyType(
    {
        ("agents.Surface", "owner_agent"): (
            "The owner agent is not used by a node that uses the surface."
        ),
        ("tables.RealtimeChannel", "realtime_agent"): (
            "The legacy agent link; calls resolve the agent definition."
        ),
        ("tables.GraphRag", "agents"): "Legacy crew agents, which never run in a flow.",
        ("tables.NaiveRag", "agents"): "Legacy crew agents, which never run in a flow.",
        ("tables.ClassificationConditionGroup", "prompt"): (
            "Names a prompt of the same decision table by its key; a run reads the prompts "
            "as children of the table."
        ),
        ("tables.ClassificationConditionGroup", "section"): (
            "A display section of the same decision table."
        ),
        ("tables.AgentNodeTask", "context_tasks"): "Earlier tasks of the same agent node.",
    }
)

# Child rows of a model the walk reaches that it does not follow: (child model, fk).
RUN_TRAVERSAL_STOPS: Mapping[tuple[str, str], str] = MappingProxyType(
    {
        ("tables.CrewNode", "graph"): "Crew nodes are never part of a run.",
        ("tables.GraphNote", "graph"): "Canvas notes.",
        ("tables.GraphVersion", "graph"): "Saved history; a run uses the current flow.",
        ("tables.GraphOrganization", "graph"): "Persistent-variable values.",
        ("tables.GraphOrganizationUser", "graph"): "Persistent-variable values.",
        ("tables.FlowAssistant", "graph"): "The flow assistant works outside runs.",
        ("tables.Session", "graph"): "A run's own record.",
        ("tables.KeyValueTableEntry", "table"): "The table's data.",
        ("tables.SessionStorageFile", "storage_file"): "Run outputs.",
        ("tables.DocumentMetadata", "source_collection"): "The collection's indexed documents.",
        ("tables.NaiveRagDocumentConfig", "naive_rag"): "Index data of the RAG.",
        ("tables.GraphRagDocument", "graph_rag"): "Index data of the RAG.",
        ("tables.AgentNaiveRag", "naive_rag"): "A legacy crew-agent link.",
        ("tables.AgentGraphRag", "graph_rag"): "A legacy crew-agent link.",
        ("tables.PythonCodeToolConfig", "tool"): (
            "Tool settings used only by legacy crew agents, which never run in a flow."
        ),
        ("tables.AgentPythonCodeTools", "pythoncodetool"): "A legacy crew-agent link.",
        ("tables.TaskPythonCodeTools", "tool"): "A legacy crew-task link.",
        ("tables.AgentMcpTools", "mcptool"): "A legacy crew-agent link.",
        ("tables.TaskMcpTools", "tool"): "A legacy crew-task link.",
        ("tables.PythonCodeToolFavorite", "tool"): "A person's favourites.",
        ("tables.McpToolFavorite", "tool"): "A person's favourites.",
    }
)

# The row each kind of run starts from.
RUN_START_MODELS: Mapping[RunKind, str] = MappingProxyType(
    {
        RunKind.FLOW: "tables.Graph",
        RunKind.REALTIME: "agents.AgentDefinition",
        RunKind.VOICE_CHANNEL: "tables.RealtimeChannel",
        RunKind.CODE: "tables.PythonCode",
    }
)

# The flag that gives a code slot of a flow node the flow's attached files and folders, as
# the converter scopes its storage. A test run of the slot can read them, so a code run
# counts them as used while the flag is on. A code slot of a flow node not listed here
# always counts them.
CODE_SLOT_STORAGE_FLAGS: Mapping[tuple[str, str], str] = MappingProxyType(
    {
        ("tables.PythonNode", "python_code"): "use_storage",
        ("tables.WebhookTriggerNode", "python_code"): "use_storage",
        ("tables.ClassificationDecisionTableNode", "pre_python_code"): "pre_use_storage",
        ("tables.ClassificationDecisionTableNode", "post_python_code"): "post_use_storage",
    }
)

_GRAPH = "tables.Graph"
_PYTHON_CODE = "tables.PythonCode"
_SECRET = "tables.Secret"
_STORAGE_FILE = "tables.StorageFile"
_FOLDER = "folder"
# The column of a marker's row that names the organization its markers resolve in.
_ORGANIZATION_COLUMN = "org_id"


class RunResourceCollector:
    """Collect what runs use by walking `RUN_REFERENCES` from their start rows.

    The number of queries depends on the table and on how deep references go (subflows
    of subflows), never on how many nodes, flows or rows there are. Organizations play no
    part in the walk: it follows ids, and callers match the result against their own
    organization's rows.

    A code run (`RunKind.CODE`) walks the code itself (its secrets) and adds, without
    walking them, the rows that hold it: a tool with that code, or the flow of a node with
    that code. A test run of one node of a flow is therefore never refused because another
    node of the same flow uses something. When the node's slot uses storage
    (`CODE_SLOT_STORAGE_FLAGS`), the flow's attached files and folders count too, since the
    test run can read them.
    """

    def collect(self, subject: RunSubject) -> RunResources:
        """Return what the run of `subject` uses."""
        return self.collect_many(subject.kind, [subject.subject_id])[subject.subject_id]

    def collect_many(self, kind: RunKind, subject_ids: Iterable[int]) -> dict[int, RunResources]:
        """Return what each run uses, keyed by subject id, in one walk for all of them.

        Ids are read as integers, so an id given as text still matches its row. Ids of rows
        that do not exist give resources holding only their start ref.
        """
        start_model = RUN_START_MODELS[kind]
        starts = {
            int(subject_id): ResourceRef(start_model, int(subject_id)) for subject_id in subject_ids
        }
        if not starts:
            return {}
        walk = _Walk(_walk_plan())
        walk.run(starts.values())
        used = {subject_id: walk.reachable_from(start) for subject_id, start in starts.items()}
        folder_paths = walk.folder_paths()
        if kind == RunKind.CODE:
            folder_paths |= _add_code_holders(starts, used)
        return {
            subject_id: RunResources(
                refs=frozenset(refs),
                storage_prefixes=frozenset(
                    folder_paths[ref.pk]
                    for ref in refs
                    if ref.model_label == _STORAGE_FILE and ref.pk in folder_paths
                ),
                secret_marker_names=walk.secret_marker_names(refs),
            )
            for subject_id, refs in used.items()
        }


def unqueried_child_references() -> frozenset[FollowChildren]:
    """Return the `FollowChildren` rows the walk never queries.

    Their child model has no reference of its own to follow, so its rows can lead nowhere
    and are left out of `RunResources.refs`.
    """
    return _walk_plan().unqueried_children


@dataclass(frozen=True)
class _ForwardField:
    attname: str
    target: str


@dataclass(frozen=True)
class _ManyToManyField:
    through_label: str
    source_attname: str
    target_attname: str
    target: str


@dataclass(frozen=True)
class _ChildLink:
    child: str
    fk_attname: str


@dataclass(frozen=True)
class _CodeSlot:
    code_attname: str
    # None on a flow node: the slot always counts the flow's attached storage.
    storage_flag: str | None


@dataclass(frozen=True)
class _CodeHolder:
    model: str
    slots: tuple[_CodeSlot, ...]
    root: str
    root_attname: str


@dataclass(frozen=True)
class _WalkPlan:
    forward_fields: Mapping[str, tuple[_ForwardField, ...]]
    # The header fields whose markers are followed, by model, as column names.
    marker_fields: Mapping[str, tuple[str, ...]]
    many_to_many_fields: Mapping[str, tuple[_ManyToManyField, ...]]
    child_links: Mapping[str, tuple[_ChildLink, ...]]
    # Child links whose child also points forward at another row of the parent's model
    # (a subflow node: its flow, and the flow it runs). Followed to a fixpoint.
    recursive_links: Mapping[str, tuple[_ChildLink, ...]]
    unqueried_children: frozenset[FollowChildren]
    model_order: tuple[str, ...]


@cache
def _walk_plan() -> _WalkPlan:
    return _build_plan(RUN_REFERENCES, RUN_SECRET_MARKERS)


@cache
def _attached_storage_plan() -> _WalkPlan:
    """The part of the walk that reaches a flow's attached files and folders.

    Taken from `RUN_REFERENCES`: the flow's child rows that lead to a storage file, and
    their fields.
    """
    fields_of: dict[str, list[FollowField]] = defaultdict(list)
    for reference in RUN_REFERENCES:
        if isinstance(reference, FollowField):
            fields_of[reference.model].append(reference)
    attachments = [
        reference
        for reference in RUN_REFERENCES
        if isinstance(reference, FollowChildren)
        and _related_label(reference.child, reference.fk) == _GRAPH
        and any(
            _related_label(field.model, field.field) == _STORAGE_FILE
            for field in fields_of[reference.child]
        )
    ]
    return _build_plan(
        (*attachments, *(field for row in attachments for field in fields_of[row.child]))
    )


def _related_label(model_label: str, field_name: str) -> str:
    return apps.get_model(model_label)._meta.get_field(field_name).related_model._meta.label


def _build_plan(
    references: tuple[FollowField | FollowChildren, ...],
    secret_markers: tuple[FollowSecretMarkers, ...] = (),
) -> _WalkPlan:
    forward_fields: dict[str, list[_ForwardField]] = defaultdict(list)
    marker_fields: dict[str, list[str]] = defaultdict(list)
    for marker in secret_markers:
        marker_fields[marker.model].append(
            apps.get_model(marker.model)._meta.get_field(marker.field).attname
        )
    many_to_many_fields: dict[str, list[_ManyToManyField]] = defaultdict(list)
    children: list[tuple[str, FollowChildren, _ChildLink]] = []
    for reference in references:
        if isinstance(reference, FollowField):
            field = apps.get_model(reference.model)._meta.get_field(reference.field)
            target = field.related_model._meta.label
            if field.many_to_many:
                through = field.remote_field.through
                many_to_many_fields[reference.model].append(
                    _ManyToManyField(
                        through_label=through._meta.label,
                        source_attname=through._meta.get_field(field.m2m_field_name()).attname,
                        target_attname=through._meta.get_field(
                            field.m2m_reverse_field_name()
                        ).attname,
                        target=target,
                    )
                )
            else:
                forward_fields[reference.model].append(_ForwardField(field.attname, target))
        else:
            field = apps.get_model(reference.child)._meta.get_field(reference.fk)
            parent = field.related_model._meta.label
            children.append((parent, reference, _ChildLink(reference.child, field.attname)))

    # A model leads somewhere if it has a field to follow, or a child that leads somewhere.
    leads_somewhere = set(forward_fields) | set(marker_fields) | set(many_to_many_fields)
    grew = True
    while grew:
        grew = False
        for parent, _, link in children:
            if link.child in leads_somewhere and parent not in leads_somewhere:
                leads_somewhere.add(parent)
                grew = True

    child_links: dict[str, list[_ChildLink]] = defaultdict(list)
    recursive_links: dict[str, list[_ChildLink]] = defaultdict(list)
    unqueried_children = set()
    for parent, reference, link in children:
        if link.child not in leads_somewhere:
            unqueried_children.add(reference)
        elif any(
            field.target == parent and field.attname != link.fk_attname
            for field in forward_fields.get(link.child, ())
        ):
            recursive_links[parent].append(link)
        else:
            child_links[parent].append(link)

    leads_to: dict[str, set[str]] = defaultdict(set)
    for model, fields in forward_fields.items():
        leads_to[model] |= {field.target for field in fields}
    for model in marker_fields:
        leads_to[model].add(_SECRET)
    for model, fields in many_to_many_fields.items():
        leads_to[model] |= {field.target for field in fields}
    for parent, links in (*child_links.items(), *recursive_links.items()):
        leads_to[parent] |= {link.child for link in links}

    return _WalkPlan(
        forward_fields=MappingProxyType({k: tuple(v) for k, v in forward_fields.items()}),
        marker_fields=MappingProxyType({k: tuple(v) for k, v in marker_fields.items()}),
        many_to_many_fields=MappingProxyType({k: tuple(v) for k, v in many_to_many_fields.items()}),
        child_links=MappingProxyType({k: tuple(v) for k, v in child_links.items()}),
        recursive_links=MappingProxyType({k: tuple(v) for k, v in recursive_links.items()}),
        unqueried_children=frozenset(unqueried_children),
        model_order=_model_order(leads_to),
    )


def _model_order(leads_to: Mapping[str, set[str]]) -> tuple[str, ...]:
    """Every model of the walk, each before the models it leads to wherever there is no cycle.

    Reverse depth-first post-order from the start models. A walk pass in this order reaches
    each model's rows before the model's turn, so it queries the model once per pass; only a
    reference back to an earlier model (a subflow, a realtime definition's agent) waits for
    the next pass.
    """
    visited: set[str] = set()
    post_order: list[str] = []

    def visit(model: str) -> None:
        visited.add(model)
        for target in sorted(leads_to.get(model, ())):
            if target not in visited:
                visit(target)
        post_order.append(model)

    every_model = set(leads_to).union(*leads_to.values())
    for model in [*RUN_START_MODELS.values(), *sorted(every_model)]:
        if model not in visited:
            visit(model)
    return tuple(reversed(post_order))


@cache
def _code_holder_plan() -> tuple[_CodeHolder, ...]:
    """Every model with a followed reference to `PythonCode`, and the root that holds it.

    A node of a flow is held by its flow; any other model holds the code itself.
    """
    slots: dict[str, list[_CodeSlot]] = defaultdict(list)
    for reference in RUN_REFERENCES:
        if not isinstance(reference, FollowField):
            continue
        field = apps.get_model(reference.model)._meta.get_field(reference.field)
        if not field.many_to_many and field.related_model._meta.label == _PYTHON_CODE:
            slots[reference.model].append(
                _CodeSlot(
                    code_attname=field.attname,
                    storage_flag=CODE_SLOT_STORAGE_FLAGS.get((reference.model, reference.field)),
                )
            )
    flow_links = {
        reference.child: apps.get_model(reference.child)._meta.get_field(reference.fk).attname
        for reference in RUN_REFERENCES
        if isinstance(reference, FollowChildren)
        and _related_label(reference.child, reference.fk) == _GRAPH
    }
    return tuple(
        _CodeHolder(
            model=model,
            slots=tuple(model_slots),
            root=_GRAPH if model in flow_links else model,
            root_attname=flow_links.get(model, "pk"),
        )
        for model, model_slots in slots.items()
    )


def _add_code_holders(
    starts: Mapping[int, ResourceRef], used: dict[int, set[ResourceRef]]
) -> dict[int, str]:
    """Add to each code run what holds its code, and the storage a flow node's slot reads.

    Returns the paths of the storage folders reached on the way, by StorageFile id.
    """
    code_ids = list(starts)
    flows_with_storage: dict[int, set[ResourceRef]] = defaultdict(set)
    for holder in _code_holder_plan():
        matches = reduce(
            or_, (Q(**{f"{slot.code_attname}__in": code_ids}) for slot in holder.slots)
        )
        columns = [slot.code_attname for slot in holder.slots] + [
            slot.storage_flag for slot in holder.slots if slot.storage_flag is not None
        ]
        rows = (
            apps.get_model(holder.model)
            ._base_manager.filter(matches)
            .values(holder.root_attname, *columns)
        )
        for row in rows:
            if row[holder.root_attname] is None:
                continue
            root = ResourceRef(holder.root, row[holder.root_attname])
            for slot in holder.slots:
                code_id = row[slot.code_attname]
                if code_id not in starts:
                    continue
                used[code_id].add(root)
                if holder.root == _GRAPH and (slot.storage_flag is None or row[slot.storage_flag]):
                    flows_with_storage[code_id].add(root)

    storage_walk = _Walk(_attached_storage_plan())
    storage_walk.run({flow for flows in flows_with_storage.values() for flow in flows})
    for code_id, flows in flows_with_storage.items():
        for flow in flows:
            used[code_id] |= storage_walk.reachable_from(flow)
    return storage_walk.folder_paths()


class _Walk:
    """One walk from many starts, recording which row led to which.

    Passes go model by model in the plan's order and query a model's newly reached rows
    together, so the number of queries depends on the table and on how often references
    lead back to an earlier model, never on how many rows there are. A row's header markers
    are read in the same query as its other fields, and the names found are looked up once
    the passes reach nothing more: one query for every name of every row.
    """

    def __init__(self, plan: _WalkPlan) -> None:
        self._plan = plan
        self._reached: set[ResourceRef] = set()
        self._edges: dict[ResourceRef, set[ResourceRef]] = defaultdict(set)
        self._fields_read: set[ResourceRef] = set()
        self._pending: dict[str, set[int]] = defaultdict(set)
        self._marker_names: dict[ResourceRef, frozenset[str]] = {}
        # (organization id, name) -> the rows whose markers name it, not yet looked up.
        self._unresolved_markers: dict[tuple[int | None, str], set[ResourceRef]] = defaultdict(set)

    def run(self, starts: Iterable[ResourceRef]) -> None:
        for start in starts:
            self._reach(None, start)
        while self._pending:
            self._run_passes()
            # A secret a marker reaches is a row like any other: its turn comes next.
            self._resolve_secret_markers()

    def secret_marker_names(self, refs: Iterable[ResourceRef]) -> frozenset[str]:
        """The names the markers of `refs` name."""
        return frozenset().union(*(self._marker_names.get(ref, ()) for ref in refs))

    def _run_passes(self) -> None:
        while self._pending:
            expanded = False
            for model_label in self._plan.model_order:
                pks = self._pending.pop(model_label, None)
                if pks:
                    expanded = True
                    pks = self._close_recursive_links(model_label, pks)
                    self._follow_forward_fields(model_label, pks)
                    self._follow_many_to_many_fields(model_label, pks)
                    self._follow_children(model_label, pks)
            # Rows of a model missing from the order would wait forever; fail instead.
            if not expanded:
                raise RuntimeError(
                    f"The run-resource walk has no place for {sorted(self._pending)}."
                )

    def reachable_from(self, start: ResourceRef) -> set[ResourceRef]:
        reached = {start}
        queue = deque([start])
        while queue:
            for target in self._edges.get(queue.popleft(), ()):
                if target not in reached:
                    reached.add(target)
                    queue.append(target)
        return reached

    def folder_paths(self) -> dict[int, str]:
        storage_pks = [ref.pk for ref in self._reached if ref.model_label == _STORAGE_FILE]
        if not storage_pks:
            return {}
        rows = (
            apps.get_model(_STORAGE_FILE)
            ._base_manager.filter(pk__in=storage_pks, item_type=_FOLDER)
            .values_list("pk", "path")
        )
        return dict(rows)

    def _reach(self, source: ResourceRef | None, target: ResourceRef) -> None:
        if source is not None:
            self._edges[source].add(target)
        if target not in self._reached:
            self._reached.add(target)
            self._pending[target.model_label].add(target.pk)

    def _follow_forward_fields(self, model_label: str, pks: set[int]) -> None:
        fields = self._plan.forward_fields.get(model_label, ())
        markers = self._plan.marker_fields.get(model_label, ())
        if not fields and not markers:
            return
        unread = [pk for pk in pks if ResourceRef(model_label, pk) not in self._fields_read]
        if not unread:
            return
        rows = (
            apps.get_model(model_label)
            ._base_manager.filter(pk__in=unread)
            .values_list("pk", *_row_columns(fields, markers))
        )
        for pk, *values in rows:
            self._record_row(ResourceRef(model_label, pk), fields, markers, values)

    def _follow_many_to_many_fields(self, model_label: str, pks: set[int]) -> None:
        for field in self._plan.many_to_many_fields.get(model_label, ()):
            rows = (
                apps.get_model(field.through_label)
                ._base_manager.filter(**{f"{field.source_attname}__in": pks})
                .values_list(field.source_attname, field.target_attname)
            )
            for source_pk, target_pk in rows:
                self._reach(
                    ResourceRef(model_label, source_pk), ResourceRef(field.target, target_pk)
                )

    def _close_recursive_links(self, model_label: str, pks: set[int]) -> set[int]:
        """Follow the model's recursive child links until they reach no new row of it.

        One query per link and level: subflows of subflows cost a query each, not a pass.
        Rows reached once are never queued again, so a cycle ends. Returns every row of
        the model found, `pks` included, for the rest of its turn.
        """
        links = self._plan.recursive_links.get(model_label)
        if not links:
            return pks
        batch, level = set(pks), set(pks)
        while level:
            for link in links:
                self._follow_child_link(model_label, link, level)
            level = self._pending.pop(model_label, set())
            batch |= level
        return batch

    def _follow_children(self, model_label: str, pks: set[int]) -> None:
        for link in self._plan.child_links.get(model_label, ()):
            self._follow_child_link(model_label, link, pks)

    def _follow_child_link(self, model_label: str, link: _ChildLink, pks: set[int]) -> None:
        # The child's own fields come in the same query, so its rows need no second read.
        fields = self._plan.forward_fields.get(link.child, ())
        markers = self._plan.marker_fields.get(link.child, ())
        rows = (
            apps.get_model(link.child)
            ._default_manager.filter(**{f"{link.fk_attname}__in": pks})
            .values_list("pk", link.fk_attname, *_row_columns(fields, markers))
        )
        for pk, parent_pk, *values in rows:
            child = ResourceRef(link.child, pk)
            self._reach(ResourceRef(model_label, parent_pk), child)
            if fields or markers:
                self._record_row(child, fields, markers, values)

    def _record_row(
        self,
        source: ResourceRef,
        fields: tuple[_ForwardField, ...],
        markers: tuple[str, ...],
        values: list,
    ) -> None:
        """Reach what one row's fields point at, and note the names its markers give."""
        self._fields_read.add(source)
        for field, value in zip(fields, values[: len(fields)], strict=True):
            if value is not None:
                self._reach(source, ResourceRef(field.target, value))
        if not markers:
            return
        organization_id, *headers = values[len(fields) :]
        names = frozenset().union(*(extract_secret_marker_names(value) for value in headers))
        if names:
            self._marker_names[source] = names
            for name in names:
                self._unresolved_markers[(organization_id, name)].add(source)

    def _resolve_secret_markers(self) -> None:
        """Reach, for each name noted since the last call, the live secret a run resolves it to."""
        if not self._unresolved_markers:
            return
        unresolved, self._unresolved_markers = self._unresolved_markers, defaultdict(set)
        names_by_organization: dict[int | None, set[str]] = defaultdict(set)
        for organization_id, name in unresolved:
            names_by_organization[organization_id].add(name)
        # The default manager, as the resolver reads: binned and system secrets never resolve.
        secrets = (
            apps.get_model(_SECRET)
            ._default_manager.filter(
                reduce(
                    or_,
                    (
                        Q(org_id=organization_id, name__in=names)
                        for organization_id, names in names_by_organization.items()
                    ),
                )
            )
            .values_list("pk", "org_id", "name")
        )
        for pk, organization_id, name in secrets:
            for source in unresolved.get((organization_id, name), ()):
                self._reach(source, ResourceRef(_SECRET, pk))


def _row_columns(fields: tuple[_ForwardField, ...], markers: tuple[str, ...]) -> tuple[str, ...]:
    """The columns `_Walk._record_row` reads: the fields to follow, then the markers' organization
    and header fields."""
    marker_columns = (_ORGANIZATION_COLUMN, *markers) if markers else ()
    return (*(field.attname for field in fields), *marker_columns)
