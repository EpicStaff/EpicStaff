from dataclasses import dataclass, field
from enum import Enum

from agents.models.agent_models import AgentDefinition
from agents.models.surface_models import Surface

from tables.models.graph_models import (
    AgentNode,
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    ConditionalEdge,
    CrewNode,
    DecisionTableNode,
    Edge,
    EndNode,
    FileExtractorNode,
    Graph,
    GraphNote,
    PythonNode,
    ScheduleTriggerNode,
    StartNode,
    SubGraphNode,
    TaskNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.llm_models import LLMConfig
from tables.models.secret_models import Secret
from tables.models.webhook_models import NgrokWebhookConfig
from tables.serializers.graph_bulk_save_serializers import (
    AgentNodeBulkSerializer,
    AudioTranscriptionNodeBulkSerializer,
    ClassificationDecisionTableNodeBulkSerializer,
    CrewNodeBulkSerializer,
    DecisionTableNodeBulkSerializer,
    EndNodeBulkSerializer,
    FileExtractorNodeBulkSerializer,
    GraphNoteBulkSerializer,
    PythonNodeBulkSerializer,
    ScheduleTriggerNodeBulkSerializer,
    StartNodeBulkSerializer,
    SubGraphNodeBulkSerializer,
    TaskNodeBulkSerializer,
    TelegramTriggerNodeBulkSerializer,
    WebhookTriggerNodeBulkSerializer,
)
from tables.services.graph_bulk_save_service.factories import (
    ClassificationDecisionTableNodeSaveableFactory,
    DefaultNodeSaveableFactory,
    DecisionTableNodeSaveableFactory,
    NodeSaveableFactory,
)


# Singletons — factories are stateless.
_DEFAULT_FACTORY = DefaultNodeSaveableFactory()
_CLASSIFICATION_DT_FACTORY = ClassificationDecisionTableNodeSaveableFactory()
_DECISION_TABLE_FACTORY = DecisionTableNodeSaveableFactory()


class ExternalRefKind(str, Enum):
    """Shape of one outward reference on a node payload — see ExternalRefField."""

    SCALAR = "scalar"  # top-level scalar FK, e.g. code_agent_node_list.llm_config
    SCALAR_LIST = "scalar_list"  # top-level list of pks (M2M), e.g. surface_list
    NESTED_OBJECT = "nested_object"  # FK inside a top-level nested object, e.g.
    # webhook_trigger.ngrok_webhook_config
    NESTED_LIST = "nested_list"  # FK inside each item of a top-level nested
    # list, e.g. prompt_configs[].llm_config


@dataclass(frozen=True)
class ExternalRefField:
    """One outward FK/M2M reference on a node type that points OUTSIDE the
    graph (LLMConfig, NgrokWebhookConfig, a subgraph Graph, Secret,
    AgentDefinition, Surface) — as opposed to intra-graph node refs like
    edges/routing, which are validated elsewhere.

    Deleting the referenced row fires the model's SET_NULL/SET_DEFAULT, but
    the live collab Redis snapshot still holds the old pk, which then fails
    the bulk-save serializer's PrimaryKeyRelatedField validation on the next
    autosave flush and wedges the whole graph's autosave forever. See
    tables/graph_collab/external_refs.py for the detection + repair pass this
    declaration drives.

    ``top_level_field`` is the payload key at the top level of a node entry —
    also what gets reported in a broadcast ``changed_fields`` list, since the
    frontend merges by top-level key. ``leaf_field`` is the field that
    actually carries the pk(s); equal to ``top_level_field`` for SCALAR and
    SCALAR_LIST, distinct for the two nested kinds (e.g. top_level_field=
    "webhook_trigger", leaf_field="ngrok_webhook_config").

    ``org_lookup`` mirrors the ORM path the field's own
    OrgScopedPrimaryKeyRelatedField/OrganizationScopedPrimaryKeyRelatedField
    uses to scope existence — ``None`` when the target model has no org field
    at all (NgrokWebhookConfig), matching that field's plain
    PrimaryKeyRelatedField (no org scoping to replicate).
    """

    top_level_field: str
    leaf_field: str
    target_model: type
    org_lookup: str | None
    kind: ExternalRefKind = ExternalRefKind.SCALAR


@dataclass
class NodeTypeConfig:
    """NodeTypeConfig contains all required data about one node type"""

    list_key: str  # key in the request payload, e.g. "crew_node_list"
    delete_key: str  # key in the deleted dict, e.g. "crew_node_ids"
    model_class: type  # Django model class, e.g. CrewNode
    serializer_class: type  # bulk serializer class, e.g. CrewNodeBulkSerializer
    saveable_factory: NodeSaveableFactory = field(default=None)
    is_singleton: bool = False  # True for at-most-one-per-graph node types (Start/End)
    # Outward (non-graph) FK/M2M refs this node type carries — see
    # ExternalRefField. Empty for node types with no such refs.
    external_ref_fields: tuple[ExternalRefField, ...] = ()

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
  2. Add one NodeTypeConfig line here. If the type is at-most-one-per-graph
     (like StartNode/EndNode), set is_singleton=True — this flag is what
     tables.graph_collab.constants derives _SINGLETON_LIST_KEYS from, which
     graph_state_service.py and snapshot_normalize.py both rely on for
     singleton-aware handling.
  Everything else (service loop, serializer fields, deletions, temp_id
  scan) updates automatically.
"""

NODE_TYPE_REGISTRY: list[NodeTypeConfig] = [
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
        "start_node_list",
        "start_node_ids",
        StartNode,
        StartNodeBulkSerializer,
        is_singleton=True,
    ),
    NodeTypeConfig(
        "end_node_list",
        "end_node_ids",
        EndNode,
        EndNodeBulkSerializer,
        is_singleton=True,
    ),
    NodeTypeConfig(
        "subgraph_node_list",
        "subgraph_node_ids",
        SubGraphNode,
        SubGraphNodeBulkSerializer,
        external_ref_fields=(
            ExternalRefField("subgraph", "subgraph", Graph, "org_id"),
        ),
    ),
    NodeTypeConfig(
        "classification_decision_table_node_list",
        "classification_decision_table_node_ids",
        ClassificationDecisionTableNode,
        ClassificationDecisionTableNodeBulkSerializer,
        saveable_factory=_CLASSIFICATION_DT_FACTORY,
        external_ref_fields=(
            ExternalRefField(
                "default_llm_config", "default_llm_config", LLMConfig, "org_id"
            ),
            ExternalRefField(
                "prompt_configs",
                "llm_config",
                LLMConfig,
                "org_id",
                kind=ExternalRefKind.NESTED_LIST,
            ),
        ),
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
        external_ref_fields=(
            ExternalRefField(
                "webhook_trigger",
                "ngrok_webhook_config",
                NgrokWebhookConfig,
                None,
                kind=ExternalRefKind.NESTED_OBJECT,
            ),
        ),
    ),
    NodeTypeConfig(
        "telegram_trigger_node_list",
        "telegram_trigger_node_ids",
        TelegramTriggerNode,
        TelegramTriggerNodeBulkSerializer,
        external_ref_fields=(
            ExternalRefField(
                "webhook_trigger",
                "ngrok_webhook_config",
                NgrokWebhookConfig,
                None,
                kind=ExternalRefKind.NESTED_OBJECT,
            ),
            ExternalRefField(
                "telegram_bot_api_key_secret_id",
                "telegram_bot_api_key_secret_id",
                Secret,
                "org_id",
            ),
        ),
    ),
    NodeTypeConfig(
        "schedule_trigger_node_list",
        "schedule_trigger_node_ids",
        ScheduleTriggerNode,
        ScheduleTriggerNodeBulkSerializer,
    ),
    NodeTypeConfig(
        "task_node_list",
        "task_node_ids",
        TaskNode,
        TaskNodeBulkSerializer,
        external_ref_fields=(
            ExternalRefField(
                "agent_definition",
                "agent_definition",
                AgentDefinition,
                "organization_id",
            ),
            ExternalRefField(
                "surface_list",
                "surface_list",
                Surface,
                "organization_id",
                kind=ExternalRefKind.SCALAR_LIST,
            ),
        ),
    ),
    NodeTypeConfig(
        "agent_node_list",
        "agent_node_ids",
        AgentNode,
        AgentNodeBulkSerializer,
        external_ref_fields=(
            ExternalRefField(
                "agent_definition",
                "agent_definition",
                AgentDefinition,
                "organization_id",
            ),
            ExternalRefField(
                "surface_list",
                "surface_list",
                Surface,
                "organization_id",
                kind=ExternalRefKind.SCALAR_LIST,
            ),
        ),
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
