from dataclasses import dataclass, field

from tables.models.graph_models import (
    AudioTranscriptionNode,
    CodeAgentNode,
    ConditionalEdge,
    CrewNode,
    DecisionTableNode,
    Edge,
    EndNode,
    FileExtractorNode,
    LLMNode,
    GraphNote,
    PythonNode,
    StartNode,
    SubGraphNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.serializers.graph_bulk_save_serializers import (
    AudioTranscriptionNodeBulkSerializer,
    CodeAgentNodeBulkSerializer,
    CrewNodeBulkSerializer,
    DecisionTableNodeBulkSerializer,
    EndNodeBulkSerializer,
    FileExtractorNodeBulkSerializer,
    LLMNodeBulkSerializer,
    GraphNoteBulkSerializer,
    PythonNodeBulkSerializer,
    StartNodeBulkSerializer,
    SubGraphNodeBulkSerializer,
    TelegramTriggerNodeBulkSerializer,
    WebhookTriggerNodeBulkSerializer,
)
from tables.services.graph_bulk_save_service.factories import (
    DefaultNodeSaveableFactory,
    DecisionTableNodeSaveableFactory,
    NodeSaveableFactory,
)


# Singletons — factories are stateless.
_DEFAULT_FACTORY = DefaultNodeSaveableFactory()
_DECISION_TABLE_FACTORY = DecisionTableNodeSaveableFactory()


@dataclass
class NodeTypeConfig:
    """NodeTypeConfig contains all required data about one node type"""

    list_key: str  # key in the request payload, e.g. "crew_node_list"
    delete_key: str  # key in the deleted dict, e.g. "crew_node_ids"
    model_class: type  # Django model class, e.g. CrewNode
    serializer_class: type  # bulk serializer class, e.g. CrewNodeBulkSerializer
    saveable_factory: NodeSaveableFactory = field(default=None)

    def __post_init__(self):
        if self.saveable_factory is None:
            self.saveable_factory = _DEFAULT_FACTORY


@dataclass
class EdgeDeleteConfig:
    """EdgeDeleteConfig contains required data for edge"""

    delete_key: str  # key in the deleted dict, e.g. "edge_ids"
    model_class: type  # Django model class, e.g. Edge


"""
NODE_TYPE_REGISTRY — single source of truth for all node types

To add a new node type:
  1. Add one BulkSerializer class in graph_bulk_save_serializers.py.
  2. Add one NodeTypeConfig line here.
  Everything else (service loop, serializer fields, deletions, temp_id
  scan) updates automatically.
"""

NODE_TYPE_REGISTRY: list[NodeTypeConfig] = [
    NodeTypeConfig(
        "code_agent_node_list",
        "code_agent_node_ids",
        CodeAgentNode,
        CodeAgentNodeBulkSerializer,
    ),
    NodeTypeConfig(
        "crew_node_list",
        "crew_node_ids",
        CrewNode,
        CrewNodeBulkSerializer,
    ),
    NodeTypeConfig(
        "python_node_list",
        "python_node_ids",
        PythonNode,
        PythonNodeBulkSerializer,
    ),
    NodeTypeConfig(
        "file_extractor_node_list",
        "file_extractor_node_ids",
        FileExtractorNode,
        FileExtractorNodeBulkSerializer,
    ),
    NodeTypeConfig(
        "audio_transcription_node_list",
        "audio_transcription_node_ids",
        AudioTranscriptionNode,
        AudioTranscriptionNodeBulkSerializer,
    ),
    NodeTypeConfig(
        "llm_node_list",
        "llm_node_ids",
        LLMNode,
        LLMNodeBulkSerializer,
    ),
    NodeTypeConfig(
        "start_node_list",
        "start_node_ids",
        StartNode,
        StartNodeBulkSerializer,
    ),
    NodeTypeConfig(
        "end_node_list",
        "end_node_ids",
        EndNode,
        EndNodeBulkSerializer,
    ),
    NodeTypeConfig(
        "subgraph_node_list",
        "subgraph_node_ids",
        SubGraphNode,
        SubGraphNodeBulkSerializer,
    ),
    NodeTypeConfig(
        "decision_table_node_list",
        "decision_table_node_ids",
        DecisionTableNode,
        DecisionTableNodeBulkSerializer,
        saveable_factory=_DECISION_TABLE_FACTORY,
    ),
    NodeTypeConfig(
        "graph_note_list",
        "graph_note_ids",
        GraphNote,
        GraphNoteBulkSerializer,
    ),
    NodeTypeConfig(
        "webhook_trigger_node_list",
        "webhook_trigger_node_ids",
        WebhookTriggerNode,
        WebhookTriggerNodeBulkSerializer,
    ),
    NodeTypeConfig(
        "telegram_trigger_node_list",
        "telegram_trigger_node_ids",
        TelegramTriggerNode,
        TelegramTriggerNodeBulkSerializer,
    ),
]


"""
EDGE_DELETE_CONFIGS — edges must be deleted before nodes (FK constraints).
Kept separate from NODE_TYPE_REGISTRY because edges are not upserted via
this registry; they have their own validation path in the service.
"""

EDGE_DELETE_CONFIGS: list[EdgeDeleteConfig] = [
    EdgeDeleteConfig("edge_ids", Edge),
    EdgeDeleteConfig("conditional_edge_ids", ConditionalEdge),
]
