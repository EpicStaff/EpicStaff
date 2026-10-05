import { AuthorshipFields } from '../authorship.model';

export interface EmbeddingConfig extends AuthorshipFields {
    id: number; // Unique identifier for the embedding config
    custom_name: string;
    model: number; // Required integer field
    task_type: 'retrieval_document'; // Required string field with an enum value
    api_key_secret_id: number | null;
    is_visible: boolean;
    /** Read-only ISO 8601 creation time; null for configs created before it was recorded. Never sent back. */
    created_at: string | null;
}

export interface GetEmbeddingConfigRequest extends AuthorshipFields {
    id: number; // Unique identifier for the embedding config
    custom_name: string;
    model: number; // Required integer field
    task_type: 'retrieval_document'; // Required string field with an enum value
    api_key_secret_id: number | null;
    is_visible: boolean;
    /** Read-only ISO 8601 creation time; null for configs created before it was recorded. Never sent back. */
    created_at: string | null;
}

export interface CreateEmbeddingConfigRequest {
    custom_name: string;
    model: number; // Required integer field
    api_key_secret_id: number | null;
    task_type?: 'retrieval_document'; // Required string field with an enum value
    is_visible?: boolean;
}

// Body of `PUT /embedding-configs/{id}/`: only the writable fields. The read-only ones
// (author, creation time, last edit) are never sent back.
export interface UpdateEmbeddingConfigRequest extends CreateEmbeddingConfigRequest {
    id: number;
}
