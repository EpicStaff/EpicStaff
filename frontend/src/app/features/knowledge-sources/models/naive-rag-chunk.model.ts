import { NaiveRagChunkStrategy } from '../enums/naive-rag-chunk-strategy';

export type DocumentChunkingProcessStatus = 'completed' | 'canceled' | 'failed' | 'timeout';

export type DocumentStatus = 'new' | 'chunking' | 'chunked' | 'indexing' | 'completed' | 'failed';

export type DocumentWithChunksStatus =
    | 'new'
    | 'chunking'
    | 'chunking_failed'
    | 'chunked'
    | 'fetching_chunks'
    | 'chunks_ready'
    | 'chunks_outdated';

export interface DocumentChunkingState {
    id: number;
    status: DocumentWithChunksStatus;
    chunkOverlap: number;
    chunkSize: number;
    chunkStrategy: NaiveRagChunkStrategy;
    chunks: NaiveRagDocumentChunk[];
    total: number;
    removedCount: number;
}

export interface NaiveRagChunkingResponse {
    chunking_job_id: string;
    naive_rag_id: number;
    document_config_id: number;
    status: DocumentChunkingProcessStatus;
    chunk_count: number;
    message: string | null;
    elapsed_time: number;
}

export interface CancelNaiveNaiveRagChunkingResponse {
    detail: string;
    naive_rag_id: number;
    document_config_id: number;
}

export interface GetNaiveRagDocumentChunksResponse {
    naive_rag_id: number;
    document_config_id: number;
    status: DocumentStatus;
    total_chunks: number;
    limit: number;
    offset: number;
    chunks: NaiveRagDocumentChunk[];
}

export interface NaiveRagDocumentChunk {
    chunk_index: number;
    preview_chunk_id: number;
    text: string;
    overlap_start_index: number | null;
    overlap_end_index: number | null;
    token_count: number | null;
    metadata: Object;
    created_at: string;
}

// --- Chunk Search ---

export interface ChunkSearchResponse {
    naive_rag_id: number;
    document_config_id: number;
    query: string;
    total_matches: number;
    limit: number;
    offset: number;
    preview_chunk_ids: number[];
}

export interface GetChunksByIdsResponse {
    naive_rag_id: number;
    document_config_id: number;
    total: number;
    chunks: NaiveRagDocumentChunk[];
}

export type ChunkSearchMode = 'none' | 'id_only' | 'id_and_text' | 'text_only';

export interface ChunkSearchState {
    mode: ChunkSearchMode;
    idFilter: number | 'all';
    textQuery: string;
    matchedChunkIds: number[];
    totalMatches: number;
    currentMatchIndex: number;
    loading: boolean;
    searchedChunks: NaiveRagDocumentChunk[];
    searchOffset: number;
    searchHasMore: boolean;
}
