import { CollectionDocument } from "./document.model";
import { CollectionNaiveRag } from "./naive-rag.model";

export enum CreateCollectionStep {
    UPLOAD_FILES = 0,
    SELECT_RAG = 1,
    CONFIGURE = 2,
}

export interface CreateCollectionDtoRequest {
    collection_name: string;
}

export enum CollectionStatus {
    EMPTY = "empty",
    UPLOADING = "uploading",
    COMPLETED = "completed",
    WARNING = "warning",
    FAILED = "failed",
}

export interface CreateCollectionDtoResponse {
    collection_id: number;
    collection_name: string;
    user_id: string,
    status: CollectionStatus,
    document_count: number,
    rag_configurations: CollectionNaiveRag[],
    created_at: string,
    updated_at: string
}

export interface GetCollectionRequest {
    collection_id: number;
    collection_name: string;
    user_id: string;
    status: CollectionStatus;
    document_count: number;
    created_at: string;
    updated_at: string;
}

export interface DeleteCollectionResponse {
    collection_id: number;
    collection_name: string;
    deleted_content: number;
    deleted_documents: number;
    message: string;
}

export interface GetCollectionRagsResponse {
    rag_id: number;
    rag_type: string;
    rag_status: string;
    collection_id: number;
    created_at: string;
    updated_at: string;
}

export interface GetCollectionDocumentsResponse {
    collection_id: number;
    collection_name: string;
    document_count: number;
    documents: Omit<CollectionDocument, 'source_collection'>[];
}
