import { AuthorshipFields } from '../authorship.model';
import { Tag } from '../tag.model';

/** How hard a reasoning model thinks before answering. `null` on a config means the provider's own default. */
export type ReasoningEffort = 'none' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';

/** Labels in canonical order, lowest effort first; the select lists them in this order. */
export const REASONING_EFFORT_LABELS: Record<ReasoningEffort, string> = {
    none: 'None',
    minimal: 'Minimal',
    low: 'Low',
    medium: 'Medium',
    high: 'High',
    xhigh: 'Extra high',
    max: 'Max',
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
    /** USD per token; null means the provider's published pricing. Set together with `output_cost_per_token`. */
    input_cost_per_token: number | null;
    /** USD per token; null means the provider's published pricing. Set together with `input_cost_per_token`. */
    output_cost_per_token: number | null;
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
    input_cost_per_token?: number | null;
    output_cost_per_token?: number | null;
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
    input_cost_per_token?: number | null;
    output_cost_per_token?: number | null;
    tags?: Tag[];
}
