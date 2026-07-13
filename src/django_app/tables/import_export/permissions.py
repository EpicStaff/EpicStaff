"""Maps import EntityType -> RBAC ResourceType for per-resource CREATE checks.

Only entity types that create org-relevant resources are listed. Types absent
from the map are not permission-gated on import (e.g. SESSION is not importable).
Tags map to their parent resource; provider models map to LLM_CONFIGS.
"""

from tables.import_export.enums import EntityType
from tables.models.rbac_models.rbac_enums import ResourceType


ENTITY_RESOURCE_MAP: dict[EntityType, ResourceType] = {
    EntityType.AGENT: ResourceType.AGENTS,
    EntityType.AGENT_TAG: ResourceType.AGENTS,
    EntityType.CREW: ResourceType.PROJECTS,
    EntityType.CREW_TAG: ResourceType.PROJECTS,
    EntityType.GRAPH: ResourceType.FLOWS,
    EntityType.GRAPH_TAG: ResourceType.FLOWS,
    EntityType.WEBHOOK_TRIGGER: ResourceType.FLOWS,
    EntityType.LABEL: ResourceType.FLOWS,
    EntityType.LLM_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.EMBEDDING_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.REALTIME_CONFIG: ResourceType.LLM_CONFIGS,
    EntityType.REALTIME_TRANSCRIPTION_CONFIG: ResourceType.LLM_CONFIGS,
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
