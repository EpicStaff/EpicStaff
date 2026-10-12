import { AuthorshipFields } from '@shared/models';

export type AgentSurfacePlace = 'all' | 'flow' | 'chat' | 'realtime';

export const FLOW_CONTEXT_PLACES: readonly AgentSurfacePlace[] = ['all', 'flow'];

export interface AgentDefaultSurface {
    surface: number;
    place: AgentSurfacePlace;
}

export type AgentMetadata = Record<string, unknown>;

/** One named instruction document. List order = the order the agent reads them in. */
export interface AgentInstruction {
    name: string;
    content: string;
}

export interface AgentDefinition extends AuthorshipFields {
    id: number;
    org: number;
    name: string;
    description: string;
    /** Read-only: every `instruction_list` content joined by a blank line, compiled by the backend. */
    instructions: string;
    instruction_list: AgentInstruction[];
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
    default_temperature: number | null;
    max_tool_calls: number;
    tool_timeout: number;
    max_consecutive_failures: number;
    schema_max_retries: number;
    /** Read-only ISO 8601 creation time; null for agents created before it was recorded. Never sent back. */
    created_at: string | null;
}

export interface CreateAgentDefinitionRequest {
    name: string;
    instruction_list?: AgentInstruction[];
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
    default_temperature?: number | null;
    max_tool_calls?: number;
    tool_timeout?: number;
    max_consecutive_failures?: number;
    schema_max_retries?: number;
}

export type PartialUpdateAgentDefinitionRequest = Partial<CreateAgentDefinitionRequest>;
