import { BaseRagType, RagStatus, RagType } from "./base-rag.model";

export interface CollectionNaiveRag {
    chunks_count: number;
    document_configs_count: number;
    embedder_id: number;
    embedder_name: string;
    embeddings_count: number;
    is_ready_for_indexing: boolean;
    message: string | null;
    rag_id: number;
    rag_type: RagType;
    status: string;
    created_at: string;
    updated_at: string;
}

export interface CreateNaiveRag {
    naive_rag_id: number;
    base_rag_type: BaseRagType<'naive'>;
    embedder: number;
    rag_status: RagStatus;
    collection_id: number;
    created_at: string;
    updated_at: string;
}

export interface CreateNaiveRagForCollectionResponse {
    message: string;
    naive_rag: CreateNaiveRag;
}
