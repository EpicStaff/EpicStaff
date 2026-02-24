import { RagName, RagTypeLevel } from "../enums/rag";

export type RagValueMap = {
    [RagName.NAIVE_RAG]: 'naive';
    [RagName.GRAPH_RAG]: 'graph';
    [RagName.HYBRID_RAG]: 'hybrid';
}

export type Rag = {
    [K in RagName]: {
        name: K;
        value: RagValueMap[K];
        description: string;
        tip: string;
        icon: string;
        level: RagTypeLevel;
        stars: number;
        disabled?: boolean;
    }
}[RagName];

export type RagType = RagValueMap[keyof RagValueMap];

export interface BaseRagType {
    rag_type_id: number;
    rag_type: 'naive';
    source_collection: number;
}

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
    base_rag_type: BaseRagType;
    embedder: number;
    rag_status: 'new';
    collection_id: number;
    created_at: string;
    updated_at: string;
}

export interface CreateRagForCollectionResponse {
    message: string;
    naive_rag: CreateNaiveRag;
}
