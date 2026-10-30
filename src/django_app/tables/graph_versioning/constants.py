from agents.models import AgentDefinition, Surface
from proxies.sandbox.models import SandboxVenvBinding

from tables.import_export.enums import EntityType, NodeType
from tables.import_export.strategies.nodes.node_maps import NODE_RELATIONS
from tables.models import (
    Graph,
    LLMConfig,
    McpTool,
    PythonCodeTool,
    WebhookTrigger,
)
from tables.services.secrets.python_code_sites import GRAPH_PYTHON_CODE_SITES

_EXCLUDED_GRAPH_SCALARS = (
    "id",
    "uuid",
    "created_at",
    "updated_at",
    "save_version",
    # The live counter, not the one the version stored, is the graph's high-water mark
    # of issued numbers.
    "node_number_seq",
)


_DEPENDENCY_ENTITY_TYPES = {
    EntityType.LLM_CONFIG.value: EntityType.LLM_CONFIG,
    EntityType.WEBHOOK_TRIGGER.value: EntityType.WEBHOOK_TRIGGER,
    EntityType.GRAPH.value: EntityType.GRAPH,
    EntityType.AGENT_DEFINITION.value: EntityType.AGENT_DEFINITION,
    EntityType.SURFACE.value: EntityType.SURFACE,
    EntityType.PYTHON_CODE_TOOL.value: EntityType.PYTHON_CODE_TOOL,
    EntityType.MCP_TOOL.value: EntityType.MCP_TOOL,
    EntityType.VENV.value: EntityType.VENV,
}

_DEPENDENCY_MODELS = {
    EntityType.LLM_CONFIG.value: LLMConfig,
    EntityType.WEBHOOK_TRIGGER.value: WebhookTrigger,
    EntityType.GRAPH.value: Graph,
    EntityType.AGENT_DEFINITION.value: AgentDefinition,
    EntityType.SURFACE.value: Surface,
    EntityType.PYTHON_CODE_TOOL.value: PythonCodeTool,
    EntityType.MCP_TOOL.value: McpTool,
    EntityType.VENV.value: SandboxVenvBinding,
}


def _node_type_for_model(model: type) -> NodeType | None:
    """Resolve the NodeType whose Graph relation is served by this model."""
    for node_type, relation_name in NODE_RELATIONS.items():
        if Graph._meta.get_field(relation_name).related_model is model:
            return node_type
    return None


def _build_venv_code_fields_by_node_type() -> dict[NodeType, tuple[str, ...]]:
    code_fields_by_node_type: dict[NodeType, list[str]] = {}
    for site in GRAPH_PYTHON_CODE_SITES:
        node_type = _node_type_for_model(site.model)
        code_fields_by_node_type.setdefault(node_type, []).append(site.code_field)
    return {
        node_type: tuple(code_fields)
        for node_type, code_fields in code_fields_by_node_type.items()
    }


#: The code slots a snapshot node can point at a venv through, by node type.
_VENV_CODE_FIELDS_BY_NODE_TYPE = _build_venv_code_fields_by_node_type()
