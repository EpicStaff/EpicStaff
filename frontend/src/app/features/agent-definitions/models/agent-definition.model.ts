export type AgentSurfacePlace = 'all' | 'flow' | 'chat' | 'realtime';

export const FLOW_CONTEXT_PLACES: readonly AgentSurfacePlace[] = ['all', 'flow'];

// UI fallbacks shown when the agent's value is null (backend null = inherit
// DefaultAgentDefinitionConfig; these mirror those org-wide defaults). Saving a
// value writes a number, i.e. it overrides the inherited default for this agent.
export const AGENT_TOOL_DEFAULTS = {
    max_tool_calls: 15,
    tool_timeout: 300,
    max_consecutive_failures: 3,
    schema_max_retries: 2,
} as const;

export interface AgentDefaultSurface {
    surface: number;
    place: AgentSurfacePlace;
}

export type InstructionsFormat = 'text' | 'markdown';

export interface AgentMetadata {
    instructions_format?: InstructionsFormat;
    [key: string]: unknown;
}

export interface AgentDefinition {
    id: number;
    organization: number;
    name: string;
    description: string;
    instructions: string;
    llm_config: number | null;
    fcm_llm_config: number | null;
    agent_definition_realtime_config_id: number | null;
    has_realtime_definition: boolean;
    default_surfaces: AgentDefaultSurface[];
    metadata: AgentMetadata;
    max_iter: number;
    max_rpm: number;
    max_execution_time: number;
    cache: boolean;
    max_retry_limit: number;
    default_temperature: number;
    max_tool_calls: number | null;
    tool_timeout: number | null;
    max_consecutive_failures: number | null;
    schema_max_retries: number | null;
}

export interface CreateAgentDefinitionRequest {
    name: string;
    instructions: string;
    description?: string;
    llm_config?: number | null;
    fcm_llm_config?: number | null;
    default_surfaces?: AgentDefaultSurface[];
    metadata?: AgentMetadata;
    max_iter?: number;
    max_rpm?: number;
    max_execution_time?: number;
    cache?: boolean;
    max_retry_limit?: number;
    default_temperature?: number;
    max_tool_calls?: number | null;
    tool_timeout?: number | null;
    max_consecutive_failures?: number | null;
    schema_max_retries?: number | null;
}

export type UpdateAgentDefinitionRequest = CreateAgentDefinitionRequest;
export type PartialUpdateAgentDefinitionRequest = Partial<CreateAgentDefinitionRequest>;
