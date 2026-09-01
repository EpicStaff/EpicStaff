import { NodeType } from '../../../../../visual-programming/core/enums/node-type';

export const HIDDEN_ENTITY_TYPES = new Set(['LLMModelTag']);

export const ENTITY_TYPE_ORDER = [
    'PythonCodeTool',
    'MCPTool',
    'Flow',
    'Project',
    'Agent',
    'LLMModel',
    'LLMConfig',
    'RealtimeModel',
    'RealtimeConfig',
];

export const FLOW_NODE_TYPE_LABELS: Partial<Record<NodeType, string>> = {
    [NodeType.PYTHON]: 'Python Node',
    [NodeType.CLASSIFICATION_TABLE]: 'Classification Decision Table',
    [NodeType.WEBHOOK_TRIGGER]: 'Webhook Node',
    [NodeType.TELEGRAM_TRIGGER]: 'Telegram Node',
    [NodeType.AGENT]: 'Agent Node',
    [NodeType.TASK]: 'Task Node',
    [NodeType.PROJECT]: 'Project Node',
};

export const ENTITY_TYPE_LABELS: Record<string, string> = {
    Agent: 'Agent',
    EmbeddingConfig: 'Embedding Config',
    EmbeddingModel: 'Embedding Model',
    EmbeddingModelTag: 'Embedding Model Tag',
    Flow: 'Flow',
    LLMConfig: 'LLM Config',
    LLMModel: 'LLM Model',
    LLMModelTag: 'LLM Model Tag',
    MCPTool: 'MCP Tool',
    Project: 'Project',
    PythonCodeTool: 'Python Code Tool',
    RealtimeConfig: 'Realtime Config',
    RealtimeModel: 'Realtime Model',
    RealtimeTranscriptionConfig: 'Realtime Transcription Config',
    RealtimeTranscriptionModel: 'Realtime Transcription Model',
    Tool: 'Tool',
};

export const ENTITY_DISPLAY_FIELDS: Record<string, { field: string; label: string }[]> = {
    Flow: [
        { field: 'description', label: 'Description' },
        { field: 'time_to_live', label: 'TTL (s)' },
        { field: 'persistent_variables', label: 'Persistent Vars' },
    ],
    Project: [
        { field: 'description', label: 'Description' },
        { field: 'process', label: 'Process' },
        { field: 'memory', label: 'Memory' },
        { field: 'max_rpm', label: 'Max RPM' },
        { field: 'planning', label: 'Planning' },
    ],
    Agent: [
        { field: 'goal', label: 'Goal' },
        { field: 'backstory', label: 'Backstory' },
    ],
    LLMModel: [
        { field: 'provider_name', label: 'Provider' },
        { field: 'predefined', label: 'Predefined' },
        { field: 'is_custom', label: 'Custom' },
    ],
    LLMConfig: [
        { field: 'temperature', label: 'Temperature' },
        { field: 'max_tokens', label: 'Max Tokens' },
        { field: 'timeout', label: 'Timeout (s)' },
    ],
    PythonCodeTool: [{ field: 'description', label: 'Description' }],
    MCPTool: [{ field: 'description', label: 'Description' }],
    Tool: [{ field: 'description', label: 'Description' }],
    RealtimeModel: [
        { field: 'provider_name', label: 'Provider' },
        { field: 'is_custom', label: 'Custom' },
    ],
    RealtimeConfig: [{ field: 'custom_name', label: 'Config Name' }],
};
