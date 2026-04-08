from tables.import_export.enums import EntityType


MAIN_ENTITY_KEY = "main_entity"
NODE_MAPPING_KEY = "node"

# Entities will be imported from top to bottom based on this list
DEPENDENCY_ORDER = (
    EntityType.AGENT_TAG,
    EntityType.CREW_TAG,
    EntityType.GRAPH_TAG,
    EntityType.LLM_MODEL_TAG,
    EntityType.LLM_CONFIG_TAG,
    EntityType.EMBEDDING_MODEL_TAG,
    EntityType.LLM_MODEL,
    EntityType.LLM_CONFIG,
    EntityType.EMBEDDING_MODEL,
    EntityType.EMBEDDING_CONFIG,
    EntityType.REALTIME_MODEL,
    EntityType.REALTIME_CONFIG,
    EntityType.REALTIME_TRANSCRIPTION_MODEL,
    EntityType.REALTIME_TRANSCRIPTION_CONFIG,
    EntityType.PYTHON_CODE_TOOL,
    EntityType.MCP_TOOL,
    EntityType.AGENT,
    EntityType.CREW,
    EntityType.WEBHOOK_TRIGGER,
    EntityType.GRAPH,
)
