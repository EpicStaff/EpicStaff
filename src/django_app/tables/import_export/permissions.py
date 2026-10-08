"""Maps import EntityType -> RBAC ResourceType for per-resource CREATE checks.

Every importable entity type that creates a top-level row must be listed, mapped
to the same ResourceType its API ViewSet gates on; a type absent from the map is
created on import without any permission check. Unlisted on purpose: SESSION
(not importable) and graph node types (created as children of a flow, which is
gated as FLOWS), and AUDIT_FILTER_PRESET (a personal saved search over audit data,
always created for the importing user in their own org; no role holds CREATE on
AUDIT, and its own import endpoint is gated on AUDIT read). Tags map to their parent resource; models and provider realtime
configs map to LLM_CONFIGS.
"""

from rbac.models.enums import ResourceType

from tables.import_export.enums import EntityType

ENTITY_RESOURCE_MAP: dict[EntityType, ResourceType] = {
    EntityType.AGENT: ResourceType.AGENTS,
    EntityType.AGENT_TAG: ResourceType.AGENTS,
    EntityType.AGENT_DEFINITION: ResourceType.AGENTS,
    EntityType.SURFACE: ResourceType.SURFACES,
    EntityType.CREW: ResourceType.PROJECTS,
    EntityType.CREW_TAG: ResourceType.PROJECTS,
    EntityType.GRAPH: ResourceType.FLOWS,
    EntityType.GRAPH_TAG: ResourceType.FLOWS,
    EntityType.WEBHOOK_TRIGGER: ResourceType.WEBHOOKS,
    EntityType.LABEL: ResourceType.FLOWS,
    EntityType.LLM_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.EMBEDDING_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.REALTIME_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.REALTIME_TRANSCRIPTION_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.OPENAI_REALTIME_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.ELEVENLABS_REALTIME_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.GEMINI_REALTIME_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.LLM_MODEL: ResourceType.LLM_CONFIGS,
    EntityType.EMBEDDING_MODEL: ResourceType.LLM_CONFIGS,
    EntityType.REALTIME_MODEL: ResourceType.LLM_CONFIGS,
    EntityType.REALTIME_TRANSCRIPTION_MODEL: ResourceType.LLM_CONFIGS,
    EntityType.LLM_CONFIG_TAG: ResourceType.LLM_CONFIGS,
    EntityType.LLM_MODEL_TAG: ResourceType.LLM_CONFIGS,
    EntityType.EMBEDDING_MODEL_TAG: ResourceType.LLM_CONFIGS,
    EntityType.PYTHON_CODE_TOOL: ResourceType.TOOLS,
    EntityType.MCP_TOOL: ResourceType.TOOLS,
}
