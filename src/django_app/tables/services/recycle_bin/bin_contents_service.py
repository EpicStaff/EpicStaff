"""Bin entries with what a restore of each would bring back: a flow's nodes, an
agent's own surfaces, a surface's tools and sources, a collection's documents."""

import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from django.db.models import Count, F, Model, Window
from django.db.models.functions import RowNumber
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
from tables.services.recycle_bin.bin_service import RecycleBinEntry, RecycleBinService
from tables.services.recycle_bin.registry import BinResource

# A row lists at most this many contents; `contents_total` has the full count.
CONTENTS_LIMIT = 100
# "Show all" sends at most this many; a bigger folder or flow says how many more there are.
SHOW_ALL_LIMIT = 5000

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


@dataclass(frozen=True)
class ContentSource:
    """Rows of `model` that belong to a bin entry through `parent_field`, named by `name_field`."""

    model: type[Model]
    parent_field: str
    name_field: str
    kind: str


def _content_sources() -> dict[str, list[ContentSource]]:
    from agents.models import (
        Surface,
        SurfaceKnowledge,
        SurfaceMcpTool,
        SurfacePythonTool,
        SurfaceStorageItem,
    )
    from tables.models import DocumentMetadata, KeyValueTableEntry

    return {
        "flow": [
            ContentSource(model, "graph_id", "node_name", node_type)
            for model, node_type in FLOW_BIN_NODE_TYPES.items()
        ],
        # An agent's own surfaces go to the bin with it and come back with it.
        "agent": [ContentSource(Surface, "owner_agent_id", "name", "surface")],
        "surface": [
            ContentSource(SurfacePythonTool, "surface_id", "python_tool__name", "python_tool"),
            ContentSource(SurfaceMcpTool, "surface_id", "mcp_tool__name", "mcp_tool"),
            ContentSource(
                SurfaceKnowledge, "surface_id", "collection__collection_name", "knowledge_source"
            ),
            ContentSource(SurfaceStorageItem, "surface_id", "storage_file__path", "file"),
        ],
        "collection": [
            ContentSource(DocumentMetadata, "source_collection_id", "file_name", "document")
        ],
        # Counted only, never named (_NAMELESS_CONTENTS): a table's keys can be private data.
        "key_value_table": [ContentSource(KeyValueTableEntry, "table_id", "key", "key")],
    }


# Resources whose contents the bin counts (contents_total) but never names: a table's
# keys can be private data, so only how many come back is shown.
_NAMELESS_CONTENTS = {"key_value_table"}


def _detail_text(text) -> str | None:
    # Sent whole: the bin shows 3 lines and the full text in a tooltip.
    if not text:
        return None
    return str(text).strip() or None


@dataclass(frozen=True)
class DetailField:
    """A detail line: `paths` are values() lookups, joined with " · " when there are several."""

    label: str
    paths: tuple[str, ...]
    format: str = "text"

    def render(self, row: dict):
        if self.format != "text":
            value = row[self.paths[0]]
            return value.isoformat() if hasattr(value, "isoformat") else value
        parts = [_detail_text(row[path]) for path in self.paths]
        return " · ".join(part for part in parts if part) or None


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


_DETAIL_FIELDS: dict[str, list[DetailField]] = {
    # Every field is always sent, null when empty, so a tab shows the same lines
    # for every row. Agents have no created/updated columns.
    "flow": [
        DetailField("Description", ("description",)),
        DetailField("Created", ("created_at",), "date"),
        DetailField("Last changed", ("updated_at",), "date"),
    ],
    "agent": [
        DetailField("Description", ("description",)),
        DetailField("Instructions", ("instructions",)),
        DetailField("LLM", ("llm_config__custom_name", "llm_config__model__name")),
    ],
    "surface": [
        DetailField("Instructions", ("instructions",)),
        DetailField("Owner agent", ("owner_agent__name",)),
        DetailField("Created", ("created_at",), "date"),
        DetailField("Last changed", ("updated_at",), "date"),
    ],
    "python_tool": [
        DetailField("Description", ("description",)),
        DetailField("Created", ("created_at",), "date"),
        DetailField("Last changed", ("updated_at",), "date"),
    ],
    "mcp_tool": [
        DetailField("Server", ("transport",)),
        DetailField("Tool name", ("tool_name",)),
        DetailField("Created", ("created_at",), "date"),
        DetailField("Last changed", ("updated_at",), "date"),
    ],
    "key_value_table": [
        DetailField("Description", ("description",)),
        DetailField("Created", ("created_at",), "date"),
        DetailField("Last changed", ("updated_at",), "date"),
    ],
    # Never the value. "Used by" comes from _secret_usage_details.
    "secret": [
        DetailField("Created", ("created_at",), "date"),
        DetailField("Last changed", ("updated_at",), "date"),
    ],
    "webhook_trigger": [
        DetailField("Provider", ("provider_type",)),
        DetailField("Domain", ("ngrok__domain", "localhost__domain")),
    ],
    "realtime_channel": [
        DetailField("Phone number", ("twilio__phone_number",)),
        DetailField("Account SID", ("twilio__account_sid",)),
        # A channel answers to a crew agent (named by its role) or an agent definition.
        DetailField(
            "Agent",
            ("realtime_agent__agent__role", "realtime_agent_definition__agent_definition__name"),
        ),
    ],
    "collection": [
        DetailField("Description", ("description",)),
        DetailField("Created", ("created_at",), "date"),
        DetailField("Last changed", ("updated_at",), "date"),
    ],
}


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
class RecycleBinEntryWithContents(RecycleBinEntry):
    details: list[BinDetail] = field(default_factory=list)
    contents: list[BinContent] = field(default_factory=list)
    contents_total: int = 0


@dataclass(frozen=True)
class _DetailContext:
    """What an extra-details provider may need besides the ids."""

    org_id: int


def _collection_index_details(
    ids: list[int], context: _DetailContext
) -> dict[int, list[BinDetail]]:
    return {
        collection_id: [BinDetail(label="Indexed", value=states)]
        for collection_id, states in _collection_indexes(ids).items()
    }


def _count_label(count: int, singular: str) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {singular}s"


# How a trigger checks its callers, as the bin names it (WebhookTriggerAuthKind).
_TRIGGER_AUTH_LABELS = {"webhook": "Webhook", "telegram": "Telegram", "twilio": "Twilio"}


def _trigger_usage_details(ids: list[int], context: _DetailContext) -> dict[int, list[BinDetail]]:
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


def _flow_trigger_details(ids: list[int], context: _DetailContext) -> dict[int, list[BinDetail]]:
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


def _voice_channel_details(ids: list[int], context: _DetailContext) -> dict[int, list[BinDetail]]:
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


def _secret_usage_details(ids: list[int], context: _DetailContext) -> dict[int, list[BinDetail]]:
    """How many resources still link to each secret (a restore reconnects them): a count, never names."""
    from tables.services.secrets import secret_usage_service

    totals = secret_usage_service.totals(org_id=context.org_id, secret_ids=set(ids))
    return {
        secret_id: [BinDetail(label="Used by", value=str(totals.get(secret_id, 0)))]
        for secret_id in ids
    }


# Lines a resource shows besides its _DETAIL_FIELDS, built once per list.
_EXTRA_DETAILS: dict[str, Callable[[list[int], _DetailContext], dict[int, list[BinDetail]]]] = {
    "collection": _collection_index_details,
    "flow": _flow_trigger_details,
    "webhook_trigger": _trigger_usage_details,
    "realtime_channel": _voice_channel_details,
    "secret": _secret_usage_details,
}


class BinContentsService:
    @classmethod
    def entries(
        cls, resource_key: str, resource: BinResource, org_id: int
    ) -> list[RecycleBinEntryWithContents]:
        """The org's bin entries for `resource`, newest first, each with what its restore brings back."""
        entries = RecycleBinService.entries(resource, org_id)
        batch_by_parent = {entry.id: entry.batch for entry in entries}
        contents, totals = cls._contents(
            _content_sources().get(resource_key, []),
            batch_by_parent,
            names=resource_key not in _NAMELESS_CONTENTS,
        )
        details = cls._details(
            resource_key, resource, list(batch_by_parent), _DetailContext(org_id=org_id)
        )
        return [
            RecycleBinEntryWithContents(
                **vars(entry),
                details=details.get(entry.id, []),
                contents=contents.get(entry.id, []),
                contents_total=totals.get(entry.id, 0),
            )
            for entry in entries
        ]

    @classmethod
    def contents_of(cls, resource_key: str, root: Model) -> tuple[list[BinContent], int]:
        """One binned root's contents, up to SHOW_ALL_LIMIT: the bin's "Show all" for that row.

        A resource whose contents are only counted (a table's keys) lists none.
        """
        contents, totals = cls._contents(
            _content_sources().get(resource_key, []),
            {root.pk: root.soft_delete_batch},
            names=resource_key not in _NAMELESS_CONTENTS,
            limit=SHOW_ALL_LIMIT,
        )
        return contents.get(root.pk, []), totals.get(root.pk, 0)

    @staticmethod
    def _contents(
        sources: list[ContentSource],
        batch_by_parent: dict[int, uuid.UUID],
        *,
        names: bool = True,
        limit: int | None = CONTENTS_LIMIT,
    ) -> tuple[dict[int, list[BinContent]], dict[int, int]]:
        """Two queries per source (one without `names`), whatever the number of entries.

        `limit` caps the names per entry (None for all of them).

        A row counts only if it's binned in its entry's own batch: that's what a
        restore of the entry brings back. One deleted on its own before has
        another batch and stays in the bin.
        """
        contents: dict[int, list[BinContent]] = defaultdict(list)
        totals: dict[int, int] = defaultdict(int)
        if not batch_by_parent:
            return contents, totals
        batches = set(batch_by_parent.values())
        for source in sources:
            rows = source.model.deleted_objects.filter(
                **{f"{source.parent_field}__in": batch_by_parent.keys()},
                soft_delete_batch__in=batches,
            )
            for parent_id, batch, count in rows.values_list(
                source.parent_field, "soft_delete_batch"
            ).annotate(count=Count("pk")):
                if batch == batch_by_parent[parent_id]:
                    totals[parent_id] += count
            if not names:
                continue
            named = rows
            if limit is not None:
                named = rows.annotate(
                    # Per (entry, batch): rows the entry lost in other deletes
                    # must not use up the cap of the batch it would restore.
                    position=Window(
                        RowNumber(),
                        partition_by=[F(source.parent_field), F("soft_delete_batch")],
                        order_by=F("pk").asc(),
                    )
                ).filter(position__lte=limit)
            for parent_id, batch, name in named.order_by("pk").values_list(
                source.parent_field, "soft_delete_batch", source.name_field
            ):
                if batch == batch_by_parent[parent_id]:
                    contents[parent_id].append(BinContent(name=name or "", kind=source.kind))
        return contents, totals

    @staticmethod
    def _details(
        resource_key: str, resource: BinResource, ids: list[int], context: "_DetailContext"
    ) -> dict[int, list[BinDetail]]:
        """Basic info per entry: one query for the whole list, plus a resource's extra lines.

        Every field of the tab is sent, with a null value when it's empty.

        Only plain descriptive fields: never secrets, URLs with credentials or keys.
        """
        fields = _DETAIL_FIELDS.get(resource_key)
        if not fields or not ids:
            return {}
        paths = {path for detail_field in fields for path in detail_field.paths}
        if resource.owner_field is not None:
            paths.add(f"{resource.owner_field}__active")
        extra_details = _EXTRA_DETAILS.get(resource_key)
        extra = extra_details(ids, context) if extra_details is not None else {}
        details: dict[int, list[BinDetail]] = {}
        for row in resource.model.all_objects.filter(pk__in=ids).values("pk", *paths):
            lines = []
            for detail_field in fields:
                lines.append(
                    BinDetail(
                        label=detail_field.label,
                        value=detail_field.render(row),
                        format=detail_field.format,
                    )
                )
            lines += extra.get(row["pk"], [])
            # False only when there is an owner and it's binned (no owner gives None):
            # RestoreService then brings the row back without its owner.
            if resource.owner_field is not None and row[f"{resource.owner_field}__active"] is False:
                lines.append(
                    BinDetail(
                        label="Comes back as",
                        value="Shared. Its owner is in the recycle bin. Restore the owner to get it back as its own.",
                        format="notice",
                    )
                )
            details[row["pk"]] = lines
        return details
