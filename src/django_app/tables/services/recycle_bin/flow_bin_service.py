"""Flows bin entries, with the nodes a restore would bring back."""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from django.db.models import Model
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
class BinNode:
    name: str
    node_type: str


@dataclass(frozen=True)
class FlowRecycleBinEntry(RecycleBinEntry):
    nodes: list[BinNode] = field(default_factory=list)


class FlowBinService:
    @classmethod
    def entries(cls, resource: BinResource, org_id: int) -> list[FlowRecycleBinEntry]:
        """Return the org's binned flows, newest first, each with its nodes."""
        entries = RecycleBinService.entries(resource, org_id)
        nodes = cls._nodes_by_flow({entry.id: entry.batch for entry in entries})
        return [
            FlowRecycleBinEntry(**vars(entry), nodes=nodes.get(entry.id, [])) for entry in entries
        ]

    @staticmethod
    def _nodes_by_flow(batch_by_flow: dict[int, uuid.UUID]) -> dict[int, list[BinNode]]:
        """One query per node model, whatever the number of flows.

        A node counts only if it's binned in its flow's own batch. A node
        deleted on its own before the flow has another batch, and a restore
        of the flow doesn't bring it back.
        """
        nodes_by_flow: dict[int, list[BinNode]] = defaultdict(list)
        if not batch_by_flow:
            return nodes_by_flow
        for model, node_type in FLOW_BIN_NODE_TYPES.items():
            rows = (
                model.deleted_objects.filter(
                    graph_id__in=batch_by_flow.keys(),
                    soft_delete_batch__in=set(batch_by_flow.values()),
                )
                .order_by("pk")
                .values_list("graph_id", "soft_delete_batch", "node_name")
            )
            for graph_id, batch, name in rows:
                if batch == batch_by_flow[graph_id]:
                    nodes_by_flow[graph_id].append(BinNode(name=name, node_type=node_type))
        return nodes_by_flow
