from agents.models import AgentDefinition, Surface
from tables.import_export.enums import EntityType
from tables.models import (
    Crew,
    Graph,
    LLMConfig,
    McpTool,
    PythonCodeTool,
    WebhookTrigger,
)

_EXCLUDED_GRAPH_SCALARS = (
    "id",
    "uuid",
    "created_at",
    "updated_at",
    "save_version",
)


_DEPENDENCY_ENTITY_TYPES = {
    EntityType.CREW.value: EntityType.CREW,
    EntityType.LLM_CONFIG.value: EntityType.LLM_CONFIG,
    EntityType.WEBHOOK_TRIGGER.value: EntityType.WEBHOOK_TRIGGER,
    EntityType.GRAPH.value: EntityType.GRAPH,
    EntityType.AGENT_DEFINITION.value: EntityType.AGENT_DEFINITION,
    EntityType.SURFACE.value: EntityType.SURFACE,
    EntityType.PYTHON_CODE_TOOL.value: EntityType.PYTHON_CODE_TOOL,
    EntityType.MCP_TOOL.value: EntityType.MCP_TOOL,
}

_DEPENDENCY_MODELS = {
    EntityType.CREW.value: Crew,
    EntityType.LLM_CONFIG.value: LLMConfig,
    EntityType.WEBHOOK_TRIGGER.value: WebhookTrigger,
    EntityType.GRAPH.value: Graph,
    EntityType.AGENT_DEFINITION.value: AgentDefinition,
    EntityType.SURFACE.value: Surface,
    EntityType.PYTHON_CODE_TOOL.value: PythonCodeTool,
    EntityType.MCP_TOOL.value: McpTool,
}

_GRAPH_RELATION_NAMES = (
    "crew_node_list",
    "subgraph_node_list",
    "python_node_list",
    "webhook_trigger_node_list",
    "file_extractor_node_list",
    "audio_transcription_node_list",
    "start_node_list",
    "decision_table_node_list",
    "classification_decision_table_node_list",
    "schedule_trigger_node_list",
    "telegram_trigger_node_list",
    "end_node",
    "graph_note_list",
    "code_agent_node_list",
    "agent_node_list",
    "task_node_list",
    "edge_list",
    "conditional_edge_list",
)
