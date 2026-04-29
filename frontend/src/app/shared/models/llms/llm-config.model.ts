import { Tag } from '../tag.model';

export interface GetLlmConfigRequest {
    id: number;
    custom_name: string;
    model: number;
    api_key: string;
    temperature: number | null;
    top_p: number | null;
    stop: string[] | null;
    max_tokens: number | null;
    presence_penalty: number | null;
    frequency_penalty: number | null;
    logit_bias: Record<string, number> | null;
    seed: number | null;
    timeout: number | null;
    is_visible: boolean;
    headers?: Record<string, string>;
    extra_headers?: Record<string, string>;
    tags: Tag[];
}

export interface CreateLLMConfigRequest {
    custom_name: string;
    model: number;
    api_key: string;
    temperature?: number | null;
    top_p?: number | null;
    stop?: string[] | null;
    max_tokens?: number | null;
    presence_penalty?: number | null;
    frequency_penalty?: number | null;
    logit_bias?: Record<string, number> | null;
    seed?: number | null;
    timeout?: number | null;
    is_visible?: boolean;
    headers?: Record<string, string>;
    extra_headers?: Record<string, string>;
    tags?: Tag[];
}

export interface UpdateLLMConfigRequest {
    id: number;
    custom_name: string;
    model: number;
    api_key: string;
    temperature?: number | null;
    top_p?: number | null;
    stop?: string[] | null;
    max_tokens?: number | null;
    presence_penalty?: number | null;
    frequency_penalty?: number | null;
    logit_bias?: Record<string, number> | null;
    seed?: number | null;
    timeout?: number | null;
    is_visible?: boolean;
    headers?: Record<string, string>;
    extra_headers?: Record<string, string>;
    tags?: Tag[];
}
