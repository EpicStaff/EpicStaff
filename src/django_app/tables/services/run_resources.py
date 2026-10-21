"""What a run uses: every row it reaches from the row it starts from.

`RUN_REFERENCES` is the walk; no other code decides what a run touches. A `FollowField` row
follows a forward FK, O2O or auto-through M2M by id, whatever the target's recycle-bin state,
because a run would use the target or fail on it. A `FollowChildren` row follows the live
rows of a child model (its default manager) whose FK points at a reached row, as a run reads
them. The walk is deliberately broad: an agent counts with both LLM configs, all its default
surfaces and its voice configs, a collection with every RAG's embedder and LLM, and an
attached folder with every file under it. Over-counting shows in what a suspension stops;
a missed reference would let a run use something it should not.

Adding a reference (a new node type, a new FK on a model the walk reaches, a new child row):
add a `FollowField` or `FollowChildren` row, or an entry in `RUN_REFERENCE_EXEMPTIONS` or
`RUN_TRAVERSAL_STOPS` with the reason it is not followed.
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
    """

    refs: frozenset[ResourceRef]
    storage_prefixes: frozenset[str]

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

_GRAPH = "tables.Graph"
_PYTHON_CODE = "tables.PythonCode"
_STORAGE_FILE = "tables.StorageFile"
_FOLDER = "folder"


class RunResourceCollector:
    """Collect what runs use by walking `RUN_REFERENCES` from their start rows.

    The number of queries depends on the table and on how deep references go (subflows
    of subflows), never on how many nodes, flows or rows there are. Organizations play no
    part in the walk: it follows ids, and callers match the result against their own
    organization's rows.

    A code run (`RunKind.CODE`) walks the code itself (its secrets) and adds, without
    walking them, the rows that hold it: a tool with that code, or the flow of a node with
    that code. A test run of one node of a flow is therefore never refused because another
    node of the same flow uses something.
    """

    def collect(self, subject: RunSubject) -> RunResources:
        """Return what the run of `subject` uses."""
        return self.collect_many(subject.kind, [subject.subject_id])[subject.subject_id]

    def collect_many(self, kind: RunKind, subject_ids: Iterable[int]) -> dict[int, RunResources]:
        """Return what each run uses, keyed by subject id, in one walk for all of them.

        Ids of rows that do not exist give resources holding only their start ref.
        """
        start_model = RUN_START_MODELS[kind]
        starts = {subject_id: ResourceRef(start_model, subject_id) for subject_id in subject_ids}
        if not starts:
            return {}
        walk = _Walk(_walk_plan())
        walk.run(starts.values())
        folder_paths = walk.folder_paths()
        holders = _code_holders(starts) if kind == RunKind.CODE else {}
        resources = {}
        for subject_id, start in starts.items():
            reached = walk.reachable_from(start)
            resources[subject_id] = RunResources(
                refs=frozenset(reached | holders.get(subject_id, set())),
                storage_prefixes=frozenset(
                    folder_paths[ref.pk]
                    for ref in reached
                    if ref.model_label == _STORAGE_FILE and ref.pk in folder_paths
                ),
            )
        return resources


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
class _CodeHolder:
    model: str
    code_attnames: tuple[str, ...]
    root: str
    root_attname: str


@dataclass(frozen=True)
class _WalkPlan:
    forward_fields: Mapping[str, tuple[_ForwardField, ...]]
    many_to_many_fields: Mapping[str, tuple[_ManyToManyField, ...]]
    child_links: Mapping[str, tuple[_ChildLink, ...]]
    code_holders: tuple[_CodeHolder, ...]
    unqueried_children: frozenset[FollowChildren]
    model_order: tuple[str, ...]


@cache
def _walk_plan() -> _WalkPlan:
    forward_fields: dict[str, list[_ForwardField]] = defaultdict(list)
    many_to_many_fields: dict[str, list[_ManyToManyField]] = defaultdict(list)
    children: list[tuple[str, FollowChildren, _ChildLink]] = []
    for reference in RUN_REFERENCES:
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
    leads_somewhere = set(forward_fields) | set(many_to_many_fields)
    grew = True
    while grew:
        grew = False
        for parent, _, link in children:
            if link.child in leads_somewhere and parent not in leads_somewhere:
                leads_somewhere.add(parent)
                grew = True

    child_links: dict[str, list[_ChildLink]] = defaultdict(list)
    unqueried_children = set()
    for parent, reference, link in children:
        if link.child in leads_somewhere:
            child_links[parent].append(link)
        else:
            unqueried_children.add(reference)

    leads_to: dict[str, set[str]] = defaultdict(set)
    for model, fields in forward_fields.items():
        leads_to[model] |= {field.target for field in fields}
    for model, fields in many_to_many_fields.items():
        leads_to[model] |= {field.target for field in fields}
    for parent, links in child_links.items():
        leads_to[parent] |= {link.child for link in links}

    return _WalkPlan(
        forward_fields=MappingProxyType({k: tuple(v) for k, v in forward_fields.items()}),
        many_to_many_fields=MappingProxyType({k: tuple(v) for k, v in many_to_many_fields.items()}),
        child_links=MappingProxyType({k: tuple(v) for k, v in child_links.items()}),
        code_holders=_plan_code_holders(children),
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


def _plan_code_holders(
    children: list[tuple[str, FollowChildren, _ChildLink]],
) -> tuple[_CodeHolder, ...]:
    """Every model with a followed reference to `PythonCode`, and the root that holds it.

    A node of a flow is held by its flow; any other model holds the code itself.
    """
    code_attnames: dict[str, list[str]] = defaultdict(list)
    for reference in RUN_REFERENCES:
        if not isinstance(reference, FollowField):
            continue
        field = apps.get_model(reference.model)._meta.get_field(reference.field)
        if not field.many_to_many and field.related_model._meta.label == _PYTHON_CODE:
            code_attnames[reference.model].append(field.attname)
    graph_links = {link.child: link.fk_attname for parent, _, link in children if parent == _GRAPH}
    return tuple(
        _CodeHolder(
            model=model,
            code_attnames=tuple(attnames),
            root=_GRAPH if model in graph_links else model,
            root_attname=graph_links.get(model, "pk"),
        )
        for model, attnames in code_attnames.items()
    )


def _code_holders(starts: Mapping[int, ResourceRef]) -> dict[int, set[ResourceRef]]:
    code_ids = list(starts)
    holders: dict[int, set[ResourceRef]] = defaultdict(set)
    for holder in _walk_plan().code_holders:
        matches = reduce(
            or_, (Q(**{f"{attname}__in": code_ids}) for attname in holder.code_attnames)
        )
        rows = (
            apps.get_model(holder.model)
            ._base_manager.filter(matches)
            .values_list(holder.root_attname, *holder.code_attnames)
        )
        for root_pk, *held_code_ids in rows:
            if root_pk is None:
                continue
            for code_id in held_code_ids:
                if code_id in starts:
                    holders[code_id].add(ResourceRef(holder.root, root_pk))
    return holders


class _Walk:
    """One walk from many starts, recording which row led to which.

    Passes go model by model in the plan's order and query a model's newly reached rows
    together, so the number of queries depends on the table and on how often references
    lead back to an earlier model, never on how many rows there are.
    """

    def __init__(self, plan: _WalkPlan) -> None:
        self._plan = plan
        self._reached: set[ResourceRef] = set()
        self._edges: dict[ResourceRef, set[ResourceRef]] = defaultdict(set)
        self._fields_read: set[ResourceRef] = set()
        self._pending: dict[str, set[int]] = defaultdict(set)

    def run(self, starts: Iterable[ResourceRef]) -> None:
        for start in starts:
            self._reach(None, start)
        while self._pending:
            for model_label in self._plan.model_order:
                pks = self._pending.pop(model_label, None)
                if pks:
                    self._follow_forward_fields(model_label, pks)
                    self._follow_many_to_many_fields(model_label, pks)
                    self._follow_children(model_label, pks)

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
        fields = self._plan.forward_fields.get(model_label)
        if not fields:
            return
        unread = [pk for pk in pks if ResourceRef(model_label, pk) not in self._fields_read]
        if not unread:
            return
        rows = (
            apps.get_model(model_label)
            ._base_manager.filter(pk__in=unread)
            .values_list("pk", *(field.attname for field in fields))
        )
        for pk, *values in rows:
            self._record_forward_fields(ResourceRef(model_label, pk), fields, values)

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

    def _follow_children(self, model_label: str, pks: set[int]) -> None:
        for link in self._plan.child_links.get(model_label, ()):
            # The child's own fields come in the same query, so its rows need no second read.
            fields = self._plan.forward_fields.get(link.child, ())
            rows = (
                apps.get_model(link.child)
                ._default_manager.filter(**{f"{link.fk_attname}__in": pks})
                .values_list("pk", link.fk_attname, *(field.attname for field in fields))
            )
            for pk, parent_pk, *values in rows:
                child = ResourceRef(link.child, pk)
                self._reach(ResourceRef(model_label, parent_pk), child)
                if fields:
                    self._record_forward_fields(child, fields, values)

    def _record_forward_fields(
        self, source: ResourceRef, fields: tuple[_ForwardField, ...], values: list
    ) -> None:
        self._fields_read.add(source)
        for field, value in zip(fields, values, strict=True):
            if value is not None:
                self._reach(source, ResourceRef(field.target, value))
