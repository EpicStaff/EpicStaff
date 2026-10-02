import { GetLlmConfigRequest } from '@shared/models';

export interface GetLLMNodeRequest {
    id: number;
    node_name: string;
    graph: number;
    llm_config: number;
    /** Nested full LLM config object (populated by backend serializer). */
    llm_config_detail?: GetLlmConfigRequest;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    metadata: Record<string, unknown>;
}
export interface CreateLLMNodeRequest {
    node_name: string;
    graph: number;
    llm_config: number;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    metadata?: Record<string, unknown>;
}
