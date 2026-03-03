from enum import Enum


class EntityType(str, Enum):
    LLM_MODEL = "LLMModel"
    LLM_CONFIG = "LLMConfig"
    EMBEDDING_MODEL = "EmbeddingModel"
    EMBEDDING_CONFIG = "EmbeddingConfig"
    REALTIME_MODEL = "RealtimeModel"
    REALTIME_CONFIG = "RealtimeConfig"
    REALTIME_TRANSCRIPTION_MODEL = "RealtimeTranscriptionModel"
    REALTIME_TRANSCRIPTION_CONFIG = "RealtimeTranscriptionConfig"
    PYTHON_CODE_TOOL = "PythonCodeTool"
    MCP_TOOL = "MCPTool"
    WEBHOOK_TRIGGER = "WebhookTrigger"
    REALTIME_AGENT = "RealtimeAgent"
    AGENT = "Agent"
    CREW = "Project"
    GRAPH = "Flow"

    AGENT_TAG = "AgentTag"
    CREW_TAG = "CrewTag"
    GRAPH_TAG = "GraphTag"
    LLM_MODEL_TAG = "LLMModelTag"
    LLM_CONFIG_TAG = "LLMConfigTag"
    EMBEDDING_MODEL_TAG = "EmbeddingModelTag"


class NodeType(str, Enum):
    START_NODE = "StartNode"
    CREW_NODE = "CrewNode"
    PYTHON_NODE = "PythonNode"
    LLM_NODE = "LLMNode"
    AUDIO_TRANSCRIPTION_NODE = "AudioTranscriptionNode"
    FILE_EXTRACTOR_NODE = "FileExtractorNode"
    TELEGRAM_TRIGGER_NODE = "TelegramTriggerNode"
    WEBHOOK_TRIGGER_NODE = "WebhookTriggerNode"
    DECISION_TABLE_NODE = "DecisionTableNode"
    SUBGRAPH_NODE = "SubgraphNode"
    END_NODE = "EndNode"
