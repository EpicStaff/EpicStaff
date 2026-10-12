"""How each recycle-bin resource shows in its bin tab: detail lines, extra lines and contents.

The types a tab is described in, and one BinPresentation per key of `bin_resources()`
(a test checks the keys match). The registry says how a resource is binned, restored
and purged; this says how the bin shows it. BinContentsService does the querying.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache

from django.db.models import F, Model
from tables.models.graph_models import (
    AgentNode,
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    DecisionTableNode,
    FileExtractorNode,
    KeyValueNode,
    KnowledgeNode,
    PythonNode,
    ScheduleTriggerNode,
    SubGraphNode,
    TaskNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)


@dataclass(frozen=True)
class ContentSource:
    """Rows of `model` that belong to a bin entry through `parent_field`, named by `name_field`."""

    model: type[Model]
    parent_field: str
    name_field: str
    kind: str


def _detail_text(text) -> str | None:
    # Sent whole: the bin shows 3 lines and the full text in a tooltip.
    if not text:
        return None
    return str(text).strip() or None


@dataclass(frozen=True)
class DetailField:
    """A detail line: `paths` are values() lookups, joined with " · " when there are several.

    `to_text` turns a stored value into its text first, for a field that isn't plain text;
    `label_for` names the line from that stored value, when one label doesn't fit every row.
    """

    label: str
    paths: tuple[str, ...]
    format: str = "text"
    to_text: Callable[[object], object] | None = None
    label_for: Callable[[object], str] | None = None

    def label_of(self, row: dict) -> str:
        return self.label if self.label_for is None else self.label_for(row[self.paths[0]])

    def render(self, row: dict):
        if self.format != "text":
            value = row[self.paths[0]]
            return value.isoformat() if hasattr(value, "isoformat") else value
        values = [row[path] for path in self.paths]
        if self.to_text is not None:
            values = [self.to_text(value) for value in values]
        parts = [_detail_text(value) for value in values]
        return " · ".join(part for part in parts if part) or None


@dataclass(frozen=True)
class BinContent:
    name: str
    kind: str


@dataclass(frozen=True)
class BinDetail:
    """One line of basic info about a bin entry. `format` tells the UI how to show `value`."""

    label: str
    value: str | int | None  # None: the field is empty
    # "text", "date" (ISO 8601), "size" (bytes) or "notice" (how the item comes back: without
    # something, or differently; the UI shows it in the accent colour)
    format: str = "text"


@dataclass(frozen=True)
class DetailContext:
    """What an extra-details builder may need besides the ids."""

    org_id: int


ExtraDetails = Callable[[list[int], DetailContext], dict[int, list[BinDetail]]]


@dataclass(frozen=True)
class BinPresentation:
    """What a resource's bin tab shows for each entry.

    Attributes:
        detail_fields: The detail lines every row sends, null when empty, so a
            tab shows the same lines for every row.
        extra_details: Builds lines the columns can't give (usage counts, notices),
            once per list: called with the entries' ids.
        content_sources: What a restore brings back with the entry. Empty for a
            resource with nothing inside.
        named_contents: False to count the contents (contents_total) but never
            name them, e.g. a table's keys, which can be private data.
    """

    detail_fields: tuple[DetailField, ...]
    extra_details: ExtraDetails | None = None
    content_sources: tuple[ContentSource, ...] = ()
    named_contents: bool = True


# Backend node model -> frontend NodeType value
# (frontend/src/app/shared/models/node/node-type.ts). Only models with a
# node_name column: start, end and notes have no name, CrewNode no frontend type.
FLOW_BIN_NODE_TYPES: dict[type[Model], str] = {
    AgentNode: "agent",
    TaskNode: "task",
    PythonNode: "python",
    KnowledgeNode: "knowledge-retriever",
    FileExtractorNode: "file-extractor",
    KeyValueNode: "key-value",
    AudioTranscriptionNode: "audio-to-text-node",
    SubGraphNode: "subgraph",
    DecisionTableNode: "table",
    ClassificationDecisionTableNode: "classification-decision-table",
    WebhookTriggerNode: "webhook-trigger",
    TelegramTriggerNode: "telegram-trigger",
    ScheduleTriggerNode: "schedule-trigger",
}


def _instructions_text(instruction_list) -> str | None:
    """One instruction document reads as plain instructions; several are listed by name, in order.

    The text of several documents can't be read in a row, and their names say what they are.
    """
    if len(instruction_list) > 1:
        return ", ".join(instruction["name"] for instruction in instruction_list)
    return instruction_list[0]["content"] if instruction_list else None


def _instructions_label(instruction_list) -> str:
    return "Instruction files" if len(instruction_list) > 1 else "Instructions"


# How each RAG status reads in the bin; anything unlisted shows as is.
_INDEX_STATES = {
    "new": "Not indexed",
    "processing": "Indexing",
    "completed": "Indexed",
    "partial": "Partly indexed",
    "outdated": "Outdated",
    "failed": "Failed",
    "cancelled": "Cancelled",
}
_NOT_INDEXED = "Not indexed"


def _collection_indexes(collection_ids: list[int]) -> dict[int, str]:
    """Each collection's search indexes and their state, e.g. "Naive RAG: Indexed · GraphRAG: Not indexed".

    The collection's own status only tracks its uploads; what a user wants to
    know is which indexes it had. Binned RAG rows count: they come back with it.
    """
    from tables.models.knowledge_models import GraphRag, NaiveRag

    labels = ("Naive RAG", "GraphRAG")
    states: dict[int, dict[str, list[str]]] = defaultdict(lambda: {label: [] for label in labels})
    for label, model in zip(labels, (NaiveRag, GraphRag), strict=True):
        rows = model.all_objects.filter(
            base_rag_type__source_collection_id__in=collection_ids
        ).values_list("base_rag_type__source_collection_id", "rag_status")
        for collection_id, status in rows:
            states[collection_id][label].append(_INDEX_STATES.get(status, status))
    return {
        collection_id: " · ".join(
            f"{label}: {', '.join(states[collection_id][label]) or _NOT_INDEXED}"
            for label in labels
        )
        for collection_id in collection_ids
    }


def _collection_index_details(ids: list[int], context: DetailContext) -> dict[int, list[BinDetail]]:
    return {
        collection_id: [BinDetail(label="Indexed", value=states)]
        for collection_id, states in _collection_indexes(ids).items()
    }


def _count_label(count: int, singular: str) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {singular}s"


# How a trigger checks its callers, as the bin names it (WebhookTriggerAuthKind).
_TRIGGER_AUTH_LABELS = {"webhook": "Webhook", "telegram": "Telegram", "twilio": "Twilio"}


def _trigger_usage_details(ids: list[int], context: DetailContext) -> dict[int, list[BinDetail]]:
    """Each trigger's auth type, and what still uses it (a restore reconnects that): live flows
    and voice channels."""
    from tables.models import TwilioChannel, WebhookTrigger

    # auth__ joins through the base manager: the auth row is binned with its trigger.
    auth_kinds = dict(WebhookTrigger.all_objects.filter(pk__in=ids).values_list("pk", "auth__kind"))

    flows_by_trigger: dict[int, set[int]] = defaultdict(set)
    for node_model in (WebhookTriggerNode, TelegramTriggerNode):
        for trigger_id, graph_id in node_model.objects.filter(
            webhook_trigger_id__in=ids, graph__active=True
        ).values_list("webhook_trigger_id", "graph_id"):
            flows_by_trigger[trigger_id].add(graph_id)
    channels_by_trigger: dict[int, int] = defaultdict(int)
    for trigger_id in TwilioChannel.objects.filter(webhook_trigger_id__in=ids).values_list(
        "webhook_trigger_id", flat=True
    ):
        channels_by_trigger[trigger_id] += 1

    details: dict[int, list[BinDetail]] = {}
    for trigger_id in ids:
        parts = []
        if flows_by_trigger[trigger_id]:
            parts.append(_count_label(len(flows_by_trigger[trigger_id]), "flow"))
        if channels_by_trigger[trigger_id]:
            parts.append(_count_label(channels_by_trigger[trigger_id], "voice channel"))
        kind = auth_kinds.get(trigger_id)
        details[trigger_id] = [
            BinDetail(label="Auth", value=_TRIGGER_AUTH_LABELS.get(kind, kind)),
            BinDetail(label="Used by", value=", ".join(parts) or None),
        ]
    return details


def _flow_trigger_details(ids: list[int], context: DetailContext) -> dict[int, list[BinDetail]]:
    """A notice on each flow that has a trigger node on a trigger in the recycle bin.

    The node keeps its link, but a binned trigger takes no calls, so the restored
    flow won't start from it until the trigger is restored too. Only nodes deleted
    with the flow count: the others don't come back with it.
    """
    paths_by_flow: dict[int, set[str]] = defaultdict(set)
    for node_model in (WebhookTriggerNode, TelegramTriggerNode):
        for flow_id, path in node_model.all_objects.filter(
            graph_id__in=ids,
            soft_delete_batch=F("graph__soft_delete_batch"),
            webhook_trigger__active=False,
        ).values_list("graph_id", "webhook_trigger__path"):
            paths_by_flow[flow_id].add(path)
    details: dict[int, list[BinDetail]] = {}
    for flow_id, paths in paths_by_flow.items():
        names = ", ".join(f'"{path}"' for path in sorted(paths))
        if len(paths) == 1:
            value = f"Its webhook trigger {names} is in the recycle bin: it won't start from it until that's restored."
        else:
            value = f"Its webhook triggers {names} are in the recycle bin: it won't start from them until they're restored."
        details[flow_id] = [BinDetail(label="Comes back", value=value, format="notice")]
    return details


def _voice_channel_details(ids: list[int], context: DetailContext) -> dict[int, list[BinDetail]]:
    """One notice per channel that won't come back answering calls as it did.

    Deleting an agent clears the channel's link to it, so a channel can come
    back with no agent. A phone number a live channel took meanwhile is dropped
    on restore (restore_hooks.drop_taken_phone_number). A channel whose webhook
    trigger is binned too keeps its link but takes no calls until that's restored.
    """
    from tables.models import RealtimeChannel, TwilioChannel

    # twilio__ joins through the base manager, so it reaches the binned Twilio rows.
    rows = list(
        RealtimeChannel.all_objects.filter(pk__in=ids).values_list(
            "pk",
            "realtime_agent_id",
            "realtime_agent_definition_id",
            "twilio__phone_number",
            "twilio__webhook_trigger__active",
            "twilio__webhook_trigger__path",
        )
    )
    taken_numbers = set(
        TwilioChannel.objects.filter(
            phone_number__in=[row[3] for row in rows if row[3]]
        ).values_list("phone_number", flat=True)
    )
    details: dict[int, list[BinDetail]] = {}
    for channel_id, agent_id, agent_definition_id, number, trigger_active, trigger_path in rows:
        notices = []
        if agent_id is None and agent_definition_id is None:
            notices.append(
                "Without an agent: it won't answer calls until you pick one in Settings."
            )
        if number in taken_numbers:
            notices.append(f"Without its phone number: {number} is in use by another channel.")
        # False only when it has a trigger and the trigger is binned (no trigger gives None).
        if trigger_active is False:
            notices.append(
                f'It can\'t take calls until its webhook trigger "{trigger_path}" is restored.'
            )
        if notices:
            details[channel_id] = [
                BinDetail(label="Comes back", value=" ".join(notices), format="notice")
            ]
    return details


def _secret_usage_details(ids: list[int], context: DetailContext) -> dict[int, list[BinDetail]]:
    """How many resources still link to each secret (a restore reconnects them): a count, never names."""
    from tables.services.secrets import secret_usage_service

    totals = secret_usage_service.totals(org_id=context.org_id, secret_ids=set(ids))
    return {
        secret_id: [BinDetail(label="Used by", value=str(totals.get(secret_id, 0)))]
        for secret_id in ids
    }


@cache
def bin_presentations() -> dict[str, BinPresentation]:
    """Every recycle-bin resource's tab, keyed like `bin_resources()`.

    Every field is always sent, null when empty, so a tab shows the same lines
    for every row. Only plain descriptive fields: never secret values, URLs with
    credentials or keys.
    """
    from agents.models import (
        Surface,
        SurfaceKnowledge,
        SurfaceMcpTool,
        SurfacePythonTool,
        SurfaceStorageItem,
    )
    from tables.models import DocumentMetadata, KeyValueTableEntry

    return {
        "flow": BinPresentation(
            detail_fields=(
                DetailField("Description", ("description",)),
                DetailField("Created", ("created_at",), "date"),
                DetailField("Last changed", ("updated_at",), "date"),
            ),
            extra_details=_flow_trigger_details,
            content_sources=tuple(
                ContentSource(model, "graph_id", "node_name", node_type)
                for model, node_type in FLOW_BIN_NODE_TYPES.items()
            ),
        ),
        # Agents have no created/updated columns.
        "agent": BinPresentation(
            detail_fields=(
                DetailField("Description", ("description",)),
                DetailField(
                    "Instructions",
                    ("instruction_list",),
                    to_text=_instructions_text,
                    label_for=_instructions_label,
                ),
                DetailField("LLM", ("llm_config__custom_name", "llm_config__model__name")),
            ),
            # An agent's own surfaces go to the bin with it and come back with it.
            content_sources=(ContentSource(Surface, "owner_agent_id", "name", "surface"),),
        ),
        "surface": BinPresentation(
            detail_fields=(
                DetailField("Instructions", ("instructions",)),
                DetailField("Owner agent", ("owner_agent__name",)),
                DetailField("Created", ("created_at",), "date"),
                DetailField("Last changed", ("updated_at",), "date"),
            ),
            content_sources=(
                ContentSource(SurfacePythonTool, "surface_id", "python_tool__name", "python_tool"),
                ContentSource(SurfaceMcpTool, "surface_id", "mcp_tool__name", "mcp_tool"),
                ContentSource(
                    SurfaceKnowledge,
                    "surface_id",
                    "collection__collection_name",
                    "knowledge_source",
                ),
                ContentSource(SurfaceStorageItem, "surface_id", "storage_file__path", "file"),
            ),
        ),
        "python_tool": BinPresentation(
            detail_fields=(
                DetailField("Description", ("description",)),
                DetailField("Created", ("created_at",), "date"),
                DetailField("Last changed", ("updated_at",), "date"),
            ),
        ),
        "mcp_tool": BinPresentation(
            detail_fields=(
                DetailField("Server", ("transport",)),
                DetailField("Tool name", ("tool_name",)),
                DetailField("Created", ("created_at",), "date"),
                DetailField("Last changed", ("updated_at",), "date"),
            ),
        ),
        "key_value_table": BinPresentation(
            detail_fields=(
                DetailField("Description", ("description",)),
                DetailField("Created", ("created_at",), "date"),
                DetailField("Last changed", ("updated_at",), "date"),
            ),
            content_sources=(ContentSource(KeyValueTableEntry, "table_id", "key", "key"),),
            # A table's keys can be private data, so only how many come back is shown.
            named_contents=False,
        ),
        "collection": BinPresentation(
            detail_fields=(
                DetailField("Description", ("description",)),
                DetailField("Created", ("created_at",), "date"),
                DetailField("Last changed", ("updated_at",), "date"),
            ),
            extra_details=_collection_index_details,
            content_sources=(
                ContentSource(DocumentMetadata, "source_collection_id", "file_name", "document"),
            ),
        ),
        # Never the value.
        "secret": BinPresentation(
            detail_fields=(
                DetailField("Created", ("created_at",), "date"),
                DetailField("Last changed", ("updated_at",), "date"),
            ),
            extra_details=_secret_usage_details,
        ),
        "realtime_channel": BinPresentation(
            detail_fields=(
                DetailField("Phone number", ("twilio__phone_number",)),
                DetailField("Account SID", ("twilio__account_sid",)),
                # A channel answers to a crew agent (named by its role) or an agent definition.
                DetailField(
                    "Agent",
                    (
                        "realtime_agent__agent__role",
                        "realtime_agent_definition__agent_definition__name",
                    ),
                ),
            ),
            extra_details=_voice_channel_details,
        ),
        "webhook_trigger": BinPresentation(
            detail_fields=(
                DetailField("Provider", ("provider_type",)),
                DetailField("Domain", ("ngrok__domain", "localhost__domain")),
            ),
            extra_details=_trigger_usage_details,
        ),
    }
