import { AuthorshipFields } from '../authorship.model';
import { CatalogConfigFields, ConfigModelReference } from '../llms/model-catalog.model';

export interface EmbeddingConfig extends AuthorshipFields, CatalogConfigFields {
    id: number; // Unique identifier for the embedding config
    custom_name: string;
    model: number; // Required integer field
    api_key_secret_id: number | null;
    is_visible: boolean;
    extra_headers: Record<string, string>;
    /** Read-only ISO 8601 creation time; null for configs created before it was recorded. Never sent back. */
    created_at: string | null;
}

export interface GetEmbeddingConfigRequest extends AuthorshipFields, CatalogConfigFields {
    id: number; // Unique identifier for the embedding config
    custom_name: string;
    model: number; // Required integer field
    api_key_secret_id: number | null;
    is_visible: boolean;
    extra_headers: Record<string, string>;
    /** Read-only ISO 8601 creation time; null for configs created before it was recorded. Never sent back. */
    created_at: string | null;
}

/** The writable fields of an embedding config besides its model. A create without `parameters` gets the model's defaults. */
interface EmbeddingConfigWriteFields {
    custom_name: string;
    api_key_secret_id: number | null;
    parameters?: Record<string, unknown>;
    connection?: Record<string, unknown>;
    is_visible?: boolean;
    extra_headers?: Record<string, string>;
}

export type CreateEmbeddingConfigRequest = EmbeddingConfigWriteFields & ConfigModelReference;

// Body of `PUT /embedding-configs/{id}/`: only the writable fields. The read-only ones
// (author, creation time, last edit) are never sent back.
export type UpdateEmbeddingConfigRequest = CreateEmbeddingConfigRequest & { id: number };
