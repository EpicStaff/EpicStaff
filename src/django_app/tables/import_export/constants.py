from tables.import_export.enums import EntityType

IMPORT_VERSION = 2

MAIN_ENTITY_KEY = "main_entity"
NODE_MAPPING_KEY = "node"

# Entities will be imported from top to bottom based on this list
DEPENDENCY_ORDER = (
    EntityType.LABEL,
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
    EntityType.OPENAI_REALTIME_CONFIG,
    EntityType.ELEVENLABS_REALTIME_CONFIG,
    EntityType.GEMINI_REALTIME_CONFIG,
    EntityType.PYTHON_CODE_TOOL,
    EntityType.MCP_TOOL,
    EntityType.SURFACE,
    EntityType.LABEL,
    EntityType.AGENT,
    EntityType.AGENT_DEFINITION,
    EntityType.CREW,
    EntityType.WEBHOOK_TRIGGER,
    EntityType.GRAPH,
    EntityType.START_NODE,
    EntityType.CREW_NODE,
    EntityType.PYTHON_NODE,
    EntityType.AUDIO_TRANSCRIPTION_NODE,
    EntityType.FILE_EXTRACTOR_NODE,
    EntityType.TELEGRAM_TRIGGER_NODE,
    EntityType.WEBHOOK_TRIGGER_NODE,
    EntityType.DECISION_TABLE_NODE,
    EntityType.CLASSIFICATION_DECISION_TABLE_NODE,
    EntityType.SUBGRAPH_NODE,
    EntityType.END_NODE,
    EntityType.NOTE_NODE,
    EntityType.SCHEDULE_TRIGGER_NODE,
    EntityType.AGENT_NODE,
    EntityType.TASK_NODE,
)
