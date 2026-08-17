export interface Secret {
    id: number;
    name: string;
    tail: string;
    metadata: Record<string, unknown> | null;
    org: number;
    created_by: number | null;
    created_at: string;
    updated_at: string;
    usage_count: number;
}

export interface CreateSecretRequest {
    name: string;
    value: string;
    metadata?: Record<string, unknown>;
}

export interface SecretUsageNodeDto {
    name: string;
    node_type: string;
    code_field: string | null;
}

export interface SecretUsageFlowItemDto {
    id: number;
    name: string;
    nodes: SecretUsageNodeDto[];
}

export type SecretUsageResourceType =
    | 'llm_config'
    | 'embedding_config'
    | 'realtime_config'
    | 'realtime_transcription_config'
    | 'mcp_tool'
    | 'python_code_tool';

export interface SecretUsageNamedItemDto {
    name: string;
    type: SecretUsageResourceType;
}

export interface SecretUsageCategoryDto {
    key: 'flows' | 'tools' | 'llm_configs';
    items: SecretUsageFlowItemDto[] | SecretUsageNamedItemDto[];
}

export interface SecretUsageResponse {
    total: number;
    categories: SecretUsageCategoryDto[];
}
