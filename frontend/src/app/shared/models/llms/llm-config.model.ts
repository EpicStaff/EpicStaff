import { AuthorshipFields } from '../authorship.model';
import { Tag } from '../tag.model';

/** How hard a reasoning model thinks before answering. `null` on a config means the provider's own default. */
export type ReasoningEffort = 'none' | 'low' | 'medium' | 'high';

export const REASONING_EFFORT_LABELS: Record<ReasoningEffort, string> = {
    none: 'None',
    low: 'Low',
    medium: 'Medium',
    high: 'High',
};

export interface GetLlmConfigRequest extends AuthorshipFields {
    id: number;
    custom_name: string;
    model: number;
    api_key_secret_id: number | null;
    temperature: number | null;
    top_p: number | null;
    stop: string[] | null;
    max_tokens: number | null;
    presence_penalty: number | null;
    frequency_penalty: number | null;
    logit_bias: Record<string, number> | null;
    seed: number | null;
    timeout: number | null;
    reasoning_effort: ReasoningEffort | null;
    is_visible: boolean;
    extra_headers?: Record<string, string>;
    tags: Tag[];
    /** Read-only ISO 8601 creation time; null for configs created before it was recorded. Never sent back. */
    created_at: string | null;
}

export interface CreateLLMConfigRequest {
    custom_name: string;
    model: number;
    api_key_secret_id: number | null;
    temperature?: number | null;
    top_p?: number | null;
    stop?: string[] | null;
    max_tokens?: number | null;
    presence_penalty?: number | null;
    frequency_penalty?: number | null;
    logit_bias?: Record<string, number> | null;
    seed?: number | null;
    timeout?: number | null;
    reasoning_effort?: ReasoningEffort | null;
    is_visible?: boolean;
    extra_headers?: Record<string, string>;
    tags?: Tag[];
}

export interface UpdateLLMConfigRequest {
    id: number;
    custom_name: string;
    model: number;
    api_key_secret_id: number | null;
    temperature?: number | null;
    top_p?: number | null;
    stop?: string[] | null;
    max_tokens?: number | null;
    presence_penalty?: number | null;
    frequency_penalty?: number | null;
    logit_bias?: Record<string, number> | null;
    seed?: number | null;
    timeout?: number | null;
    reasoning_effort?: ReasoningEffort | null;
    is_visible?: boolean;
    extra_headers?: Record<string, string>;
    tags?: Tag[];
}
