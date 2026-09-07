from __future__ import annotations

"""Single source of truth for the node types the Flow Assistant knows about.

`tools.py` and `service.py` derive every node-table list, node count, node
index, and display-name fallback from `FLOW_ASSISTANT_NODE_TYPES` below
instead of keeping their own hardcoded copies. Before this module existed,
four call sites carried independent literals that drifted apart — see the
flow assistant repair plan for the incident history.

Named `FLOW_ASSISTANT_NODE_TYPES` (not `NODE_TYPE_REGISTRY`) to avoid
colliding with `graph_bulk_save_service/registry.py`'s `NODE_TYPE_REGISTRY`,
a separate list serving a separate concern (bulk save/delete) in the same
Django app.
"""

from dataclasses import dataclass
from typing import Literal

from tables.models.graph_models import (
    AgentNode,
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    ConditionalEdge,
    CrewNode,
    DecisionTableNode,
    EndNode,
    FileExtractorNode,
    PythonNode,
    ScheduleTriggerNode,
    StartNode,
    SubGraphNode,
    TaskNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)

NodeNameSource = Literal["column", "property", "synthesized"]


@dataclass(frozen=True)
class NodeTypeSpec:
    """Describes one executable node type and how to read it off a Graph.

    label: snake_case type token used throughout the flow assistant (tool
        outputs, system prompt, node index).
    model: the Django model class backing this node type.
    related_name: the Graph FK related_name exposing this node type's
        queryset. This is also the cross-layer contract shared with
        GraphSerializer and (for types that reach the crew service) the
        crew's GraphData fields.
    node_name_source: where a display name comes from for this type —
        "column" when `node_name` is a real database column (safe to pass to
        `.only()`), "property" when it's a Python @property computed off the
        instance (StartNode, EndNode — passing "node_name" to `.only()` for
        those raises FieldDoesNotExist), or "synthesized" when the model has
        no `node_name` attribute at all, neither column nor property
        (ConditionalEdge), so a display name must be built from the type
        label and pk instead.
    is_edge: True for types the rest of the platform treats as an edge, not
        a node (currently only ConditionalEdge — see
        graph_bulk_save_service/registry.py's EDGE_DELETE_CONFIGS). Such
        types stay in the node index (useful for resolving edge endpoints)
        but are excluded from node counts/listings and folded into edge
        counts instead.
    deprecated: True for types that new flows cannot create but existing
        graphs may still contain (currently only CrewNode, superseded by
        AgentNode/TaskNode).
    """

    label: str
    model: type
    related_name: str
    node_name_source: NodeNameSource = "column"
    is_edge: bool = False
    deprecated: bool = False

    def only_fields(self) -> list[str]:
        """Columns to pass to `.only()` for a lightweight index/listing query."""
        return ["id", "node_name"] if self.node_name_source == "column" else ["id"]

    def display_name(self, node) -> str:
        """Best-effort human-readable name for one instance of this node type.

        For StartNode/EndNode, node_name is a @property returning a fixed
        string ("__start__" / "__end_node__") — getattr picks that up
        unchanged. For ConditionalEdge, which has no node_name attribute at
        all, this synthesizes "conditional_edge_{pk}".
        """
        if self.node_name_source == "synthesized":
            return f"{self.label}_{node.pk}"
        return getattr(node, "node_name", "") or f"{self.label}_{node.pk}"


# Node types the Flow Assistant treats as executable graph steps. Order is
# preserved in prompt output and tool responses that iterate the registry.
FLOW_ASSISTANT_NODE_TYPES: tuple[NodeTypeSpec, ...] = (
    NodeTypeSpec("python", PythonNode, "python_node_list"),
    NodeTypeSpec("file_extractor", FileExtractorNode, "file_extractor_node_list"),
    NodeTypeSpec(
        "audio_transcription", AudioTranscriptionNode, "audio_transcription_node_list"
    ),
    NodeTypeSpec("subgraph", SubGraphNode, "subgraph_node_list"),
    NodeTypeSpec("start", StartNode, "start_node_list", node_name_source="property"),
    NodeTypeSpec("end", EndNode, "end_node", node_name_source="property"),
    NodeTypeSpec("decision_table", DecisionTableNode, "decision_table_node_list"),
    NodeTypeSpec(
        "classification_decision_table",
        ClassificationDecisionTableNode,
        "classification_decision_table_node_list",
    ),
    NodeTypeSpec("webhook_trigger", WebhookTriggerNode, "webhook_trigger_node_list"),
    NodeTypeSpec("telegram_trigger", TelegramTriggerNode, "telegram_trigger_node_list"),
    NodeTypeSpec("agent", AgentNode, "agent_node_list"),
    NodeTypeSpec("task", TaskNode, "task_node_list"),
    NodeTypeSpec("schedule_trigger", ScheduleTriggerNode, "schedule_trigger_node_list"),
    NodeTypeSpec(
        "conditional_edge",
        ConditionalEdge,
        "conditional_edge_list",
        node_name_source="synthesized",
        is_edge=True,
    ),
    # DEPRECATED: CrewNode only exists in legacy graphs pre-dating
    # AgentNode/TaskNode. New flows cannot create one, but the assistant
    # must still be able to describe existing ones.
    NodeTypeSpec("crew", CrewNode, "crew_node_list", deprecated=True),
)

# Reverse lookup used by get_node() to map a model instance (found via
# BaseGlobalNode.find_globally) back to its spec in one dict lookup, without
# rebuilding a 15-table index. Also acts as the allowlist that keeps
# find_globally from resolving node types the Flow Assistant doesn't know
# about — e.g. GraphNote (a canvas sticky note, not an executable step) is a
# BaseGlobalNode subclass too, but since it's absent from
# FLOW_ASSISTANT_NODE_TYPES it's absent here and get_node correctly rejects
# it instead of returning a note as if it were a node.
NODE_TYPE_SPEC_BY_MODEL: dict[type, NodeTypeSpec] = {
    spec.model: spec for spec in FLOW_ASSISTANT_NODE_TYPES
}
