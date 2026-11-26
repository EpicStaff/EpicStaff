import { AuthorshipFields } from '../authorship.model';
import { Tag } from '../tag.model';
import { CatalogConfigFields, ConfigModelReference } from './model-catalog.model';

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

export interface GetLlmConfigRequest extends AuthorshipFields, CatalogConfigFields {
    id: number;
    custom_name: string;
    model: number;
    api_key_secret_id: number | null;
    timeout: number | null;
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

/** The writable fields of an LLM config besides its model. A create without `parameters` gets the model's defaults. */
interface LlmConfigWriteFields {
    custom_name: string;
    api_key_secret_id: number | null;
    parameters?: Record<string, unknown>;
    connection?: Record<string, unknown>;
    timeout?: number | null;
    is_visible?: boolean;
    extra_headers?: Record<string, string>;
    input_cost_per_token?: number | null;
    output_cost_per_token?: number | null;
    tags?: Tag[];
}

export type CreateLLMConfigRequest = LlmConfigWriteFields & ConfigModelReference;

export type UpdateLLMConfigRequest = LlmConfigWriteFields & ConfigModelReference & { id: number };
