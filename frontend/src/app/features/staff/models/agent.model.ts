import { AgentSearchConfigs } from '../../../shared/models';
import { GetMcpToolRequest } from '../../tools/models/mcp-tool.model';
import { GetPythonCodeToolRequest } from '../../tools/models/python-code-tool.model';
import { GetToolRequest } from '../../tools/models/tool.model';
import { GetToolConfigRequest } from '../../tools/models/tool-config.model';

export type ToolUniqueName = `configured-tool:${number}` | `python-code-tool:${number}` | `mcp-tool:${number}`;

export interface Agent {
    id: number;

    role: string;
    goal: string;
    backstory: string;

    configured_tools: number[];
    python_code_tools: number[];

    llm_config: number | null;
    fcm_llm_config: number | null;

    allow_delegation: boolean;
    memory: boolean;

    max_iter: number;
    max_rpm: number | null;
    max_execution_time: number | null;
    cache: boolean | null;
    allow_code_execution: boolean | null;
    max_retry_limit: number | null;
    respect_context_window: boolean | null;
    default_temperature: number | null;

    knowledge_collection: number | null;

    realtime_agent: RealtimeAgentConfig;
    tools: {
        unique_name: ToolUniqueName;
        data: GetToolRequest | GetPythonCodeToolRequest | GetMcpToolRequest;
    }[];
}

export interface RealtimeAgentConfig {
    wake_word: string | null;
    stop_prompt: string | null;
    language: string | null;
    voice_recognition_prompt: string | null;
    voice: string;
    realtime_config: number | null;
    realtime_transcription_config: number | null;
}
export interface GetAgentRequest {
    id: number;

    role: string;
    goal: string;
    backstory: string;

    configured_tools: number[];
    python_code_tools: number[];
    mcp_tools: number[];

    llm_config: number | null;
    fcm_llm_config: number | null;

    allow_delegation: boolean;
    memory: boolean;

    max_iter: number;
    max_rpm: number | null;
    max_execution_time: number | null;
    cache: boolean | null;
    allow_code_execution: boolean | null;
    max_retry_limit: number | null;
    respect_context_window: boolean | null;
    default_temperature: number | null;

    knowledge_collection: number | null;
    rag: AgentRag | null;
    realtime_agent: RealtimeAgentConfig;
    tools: {
        unique_name: ToolUniqueName;
        data: GetToolConfigRequest | GetPythonCodeToolRequest | GetMcpToolRequest;
    }[];

    search_configs: AgentSearchConfigs | null;
}

// Create Agent Request
export interface CreateAgentRequest {
    role: string;
    goal: string;
    backstory: string;

    configured_tools?: number[];
    python_code_tools?: number[];
    mcp_tools?: number[];

    llm_config?: number | null;
    fcm_llm_config?: number | null;

    allow_delegation?: boolean;
    memory?: boolean;

    max_iter?: number;
    max_rpm?: number | null;
    max_execution_time?: number | null;
    cache?: boolean | null;
    allow_code_execution?: boolean | null;
    max_retry_limit?: number | null;
    respect_context_window?: boolean | null;
    default_temperature?: number | null;
    knowledge_collection?: number | null;
    rag: AgentRag | null;
    realtime_agent?: RealtimeAgentConfig;
    tool_ids: ToolUniqueName[];
    search_configs: AgentSearchConfigs | null;
}

// partialUpdate Agent Request
export interface PartialUpdateAgentRequest extends Partial<UpdateAgentRequest> {}

// Update Agent Request
export interface UpdateAgentRequest {
    id: number;
    role: string;
    goal: string;
    backstory: string;

    configured_tools: number[];
    python_code_tools: number[];
    mcp_tools: number[];

    llm_config: number | null;
    fcm_llm_config: number | null;

    allow_delegation: boolean;
    memory: boolean;

    max_iter: number;
    max_rpm: number | null;
    max_execution_time: number | null;
    cache: boolean | null;
    allow_code_execution: boolean | null;
    max_retry_limit: number | null;
    respect_context_window: boolean | null;
    default_temperature: number | null;

    knowledge_collection: number | null;
    rag: AgentRag | null;
    realtime_agent: RealtimeAgentConfig;
    tool_ids: ToolUniqueName[];

    search_configs: AgentSearchConfigs | null;
}

export interface AgentRag {
    rag_id: number;
    rag_type: string;
    rag_status?: string;
}

export type AgentTableItem = Omit<Agent, 'id'> & {
    id: number | null;
};

export interface AgentNode {
    id: number;
    type: 'agent' | 'task';
    reference_id: number;
}
