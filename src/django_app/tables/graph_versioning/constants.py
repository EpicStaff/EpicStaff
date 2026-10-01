from agents.models import AgentDefinition, Surface

from tables.import_export.enums import EntityType
from tables.models import (
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
    EntityType.LLM_CONFIG.value: EntityType.LLM_CONFIG,
    EntityType.WEBHOOK_TRIGGER.value: EntityType.WEBHOOK_TRIGGER,
    EntityType.GRAPH.value: EntityType.GRAPH,
    EntityType.AGENT_DEFINITION.value: EntityType.AGENT_DEFINITION,
    EntityType.SURFACE.value: EntityType.SURFACE,
    EntityType.PYTHON_CODE_TOOL.value: EntityType.PYTHON_CODE_TOOL,
    EntityType.MCP_TOOL.value: EntityType.MCP_TOOL,
}

_DEPENDENCY_MODELS = {
    EntityType.LLM_CONFIG.value: LLMConfig,
    EntityType.WEBHOOK_TRIGGER.value: WebhookTrigger,
    EntityType.GRAPH.value: Graph,
    EntityType.AGENT_DEFINITION.value: AgentDefinition,
    EntityType.SURFACE.value: Surface,
    EntityType.PYTHON_CODE_TOOL.value: PythonCodeTool,
    EntityType.MCP_TOOL.value: McpTool,
}
