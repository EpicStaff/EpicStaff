export type AgentSurfacePlace = 'all' | 'flow' | 'chat';

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
    default_surfaces: AgentDefaultSurface[];
    metadata: AgentMetadata;
    max_iter: number;
    max_rpm: number;
    max_execution_time: number;
    cache: boolean;
    max_retry_limit: number;
    default_temperature: number;
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
}

export type UpdateAgentDefinitionRequest = CreateAgentDefinitionRequest;
export type PartialUpdateAgentDefinitionRequest = Partial<CreateAgentDefinitionRequest>;
