import { JsonSchema, SchemaFieldError } from '../json-schema.model';

/** What a model is used for; selects which providers, models and settings the catalog offers. */
export type ModelKind = 'llm' | 'embedding' | 'transcription';

/** `GET ai-models/providers/?kind=`: one provider a config of that kind can use, recommended first. */
export interface CatalogProvider {
    name: string;
    label: string;
    recommended: boolean;
    /** A model name the catalog does not know may be typed for this provider. */
    custom_models: boolean;
}

/** `GET ai-models/models/?kind=&provider=&search=`: one model; models past their deprecation date are left out. */
export interface CatalogModel {
    name: string;
    recommended: boolean;
    /** ISO date (`YYYY-MM-DD`), or null when none is known. */
    deprecation_date: string | null;
    /** Model limits such as `max_output_tokens`. */
    limits: Record<string, number>;
}

/** `GET ai-models/schemas/?kind=&provider=&model=`: what a config of one model may hold. */
export interface ModelSchemas {
    /** The model's settings; a model the catalog does not know gets its provider's common settings. */
    parameters: JsonSchema;
    /** The provider's connection fields; a secret field (`x-widget: 'secret'`) takes an `epicstaff_secret(<name>)` marker. */
    connection: JsonSchema;
    /** The settings a new config starts with; a setting that is "not set" by default is left out. */
    defaults: Record<string, unknown>;
}

/** One entry of `errors` in a refused config write; `field` is e.g. `parameters.temperature` or `connection.base_url`. */
export interface ConfigFieldError extends SchemaFieldError {
    /** Left out for a secret connection field. */
    value?: unknown;
}

/** The catalog-backed fields a stored LLM or embedding config carries. */
export interface CatalogConfigFields {
    /** Read-only: the name of the model's provider row (`openai`, `google_ai`); null when the config has no model. */
    provider: string | null;
    /** Read-only: the name of the config's model row; null when the config has no model. */
    model_name: string | null;
    /** The model's settings, every one stored explicitly. */
    parameters: Record<string, unknown>;
    /** The provider's connection fields (endpoint, region, …); a secret one holds an `epicstaff_secret(<name>)` marker. */
    connection: Record<string, string>;
    /** Read-only: the model or settings no longer match the catalog. The config still runs. */
    needs_review: boolean;
    /** Read-only: why `needs_review` is set. */
    review_reasons: string[];
}

/**
 * How a config write names its model: a model row id, or the catalog provider and model name (a name the catalog does
 * not know creates or reuses the organization's custom model row).
 */
export type ConfigModelReference = { model: number } | { provider: string; model_name: string };
