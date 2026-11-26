export interface EmbeddingModel {
    id: number;
    name: string;
    predefined: boolean;
    embedding_provider?: number;
    is_visible: boolean;
    is_custom: boolean;
}

export interface CreateEmbeddingModelRequest {
    name: string;
    description?: string | null;
    is_visible: boolean;
    embedding_provider: number;
}
