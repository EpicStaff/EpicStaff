import { BaseRagType, RagStatus, RagType } from './base-rag.model';

export type GraphRagFileType = 'csv' | 'text' | 'json';
export type GraphRagChunkStrategy = 'tokens' | 'sentence';

export interface CollectionDetailsGraphRag {
    embedder_id: string;
    embedder_name: string;
    is_ready_for_indexing: boolean;
    message: string | null;
    rag_id: number;
    rag_type: RagType;
    require_reindexing: boolean;
    reindex_reason: Record<string, string>;
    status: RagStatus;
    created_at: string;
    updated_at: string;
}

export interface CollectionGraphRag {
    graph_rag_id: number;
    base_rag_type: BaseRagType<'graph'>;
    embedder: number;
    embedder_name: string;
    llm: number;
    llm_name: string;
    rag_status: RagStatus;
    collection_id: number;
    collection_name: string;
    index_config: GraphRagIndexConfig;
    total_documents_in_collection: number;
    documents_in_graph_rag: number;
    error_message: string | null;
    created_at: string;
    updated_at: string;
    indexed_at: string | null;
}

export interface GraphRagIndexConfig {
    id: number;
    file_type: GraphRagFileType;
    chunk_size: number;
    chunk_overlap: number;
    chunk_strategy: GraphRagChunkStrategy;
    entity_types: string[];
    max_gleanings: number;
    max_cluster_size: number;
}

export interface CreateGraphRagForCollectionResponse {
    message: string;
    graph_rag: CollectionGraphRag;
}

export interface CreateGraphRagIndexConfigRequest {
    file_type: GraphRagFileType;
    chunk_size: number;
    chunk_overlap: number;
    chunk_strategy: GraphRagChunkStrategy;
    entity_types: string[];
    max_gleanings: number;
    max_cluster_size: number;
}
