import { NaiveRagChunkStrategy } from "../enums/naive-rag-chunk-strategy";
import { RagType } from "./naive-rag.model";

export type NaiveRagDocumentStatus =
    | 'new'
    | 'chunking'
    | 'chunked'
    | 'indexing'
    | 'completed'
    | 'warning'
    | 'failed';

export type NaiveRagAdditionalParams = {
    [key in NaiveRagChunkStrategy]: any;
};

export interface NaiveRagDocumentConfig {
    naive_rag_document_id: number;
    document_id: number;
    file_name: string;
    chunk_strategy: NaiveRagChunkStrategy;
    chunk_size: number;
    chunk_overlap: number;
    additional_params: NaiveRagAdditionalParams;
    status: NaiveRagDocumentStatus;
    total_chunks: number;
    total_embeddings: number;
    created_at: string;
    processed_at: string | null;
}

export interface InitNaiveRagDocumentsResponse {
    message: string;
    configs_created: number;
    configs_existing: number;
    new_configs: any[];
}

export interface GetNaiveRagDocumentConfigsResponse {
    naive_rag_id: number;
    total_configs: number;
    configs: NaiveRagDocumentConfig[];
}

export interface UpdateNaiveRagDocumentDtoRequest {
    chunk_size?: number;
    chunk_overlap?: number;
    chunk_strategy?: NaiveRagChunkStrategy;
    additional_params?: {};
}

export interface BulkUpdateNaiveRagDocumentDtoRequest extends UpdateNaiveRagDocumentDtoRequest {
    config_ids: number[];
}

export interface UpdateNaiveRagDocumentConfigError {
    field: keyof NaiveRagDocumentConfig;
    value: string | number;
    reason: string;
}

interface UpdatedNaiveRagDocumentConfig extends NaiveRagDocumentConfig {
    errors: UpdateNaiveRagDocumentConfigError[];
}

export interface BulkUpdateNaiveRagDocumentDtoResponse {
    configs: UpdatedNaiveRagDocumentConfig[];
    failed_count: number;
    message: string;
    updated_count: number;
}

export interface BulkDeleteNaiveRagDocumentDtoRequest {
    config_ids: number[];
}

export interface BulkDeleteNaiveRagDocumentDtoResponse {
    deleted_config_ids: number[];
    deleted_count: number;
    message: string;
}

export interface UpdateNaiveRagDocumentResponse {
    message: string;
    config: NaiveRagDocumentConfig;
}

export interface StartIndexingDtoRequest {
    rag_id: number;
    rag_type: RagType;
}

export interface StartIndexingDtoResponse {
    detail: string;
    rag_id: number;
    rag_type: string;
    collection_id: number;
}
