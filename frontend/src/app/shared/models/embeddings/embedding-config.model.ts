export interface EmbeddingConfig {
    id: number; // Unique identifier for the embedding config
    custom_name: string;
    model: number; // Required integer field
    task_type: 'retrieval_document'; // Required string field with an enum value
    api_key_secret_id: number | null;
    is_visible: boolean;
}

export interface GetEmbeddingConfigRequest {
    id: number; // Unique identifier for the embedding config
    custom_name: string;
    model: number; // Required integer field
    task_type: 'retrieval_document'; // Required string field with an enum value
    api_key_secret_id: number | null;
    is_visible: boolean;
}

export interface CreateEmbeddingConfigRequest {
    custom_name: string;
    model: number; // Required integer field
    api_key_secret_id: number | null;
    task_type?: 'retrieval_document'; // Required string field with an enum value
    is_visible?: boolean;
}
