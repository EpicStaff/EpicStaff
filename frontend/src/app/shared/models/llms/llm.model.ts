export interface LLMModel {
    id: number;
    name: string;
    description: string | null;
    base_url: string | null;
    deployment_id: string | null;
    api_version: string | null;
    is_visible: boolean;
    is_custom: boolean;
    predefined: boolean; // seeded catalog row; drives the "Deprecated" badge and list sort order

    llm_provider: number;
}

export interface GetLlmModelRequest {
    id: number;
    name: string;
    description: string | null;
    base_url: string | null;
    deployment_id: string | null;
    api_version: string | null;
    is_visible: boolean;
    is_custom: boolean;
    predefined: boolean;

    llm_provider: number;
}

export interface CreateLlmModelRequest {
    name: string;
    description?: string | null;
    base_url?: string | null;
    deployment_id?: string | null;
    api_version?: string | null;
    is_visible: boolean;
    llm_provider: number;
}
