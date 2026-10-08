import { FILE_TYPES } from '../constants/constants';

export interface UploadDocumentResponse {
    message: string;
    documents: CollectionDocument[];
}

export interface CopyDocumentsRequest {
    collection_id: number;
    document_ids: number[];
}

export interface CopyDocumentsResponse {
    message: string;
    documents: CollectionDocument[];
}

export interface ImportFromStorageRequest {
    /** Storage file and/or folder ids, exactly as dragged — the server expands folders. */
    storage_file_ids: number[];
}

export type StorageImportSkipReason = 'unsupported_type' | 'too_large' | 'duplicate';

export interface StorageImportSkippedFile {
    storage_file_id: number;
    path: string;
    reason: StorageImportSkipReason;
}

/** 201 body of `POST documents/source-collection/{id}/from-storage/`. */
export interface ImportFromStorageResponse {
    message: string;
    documents: CollectionDocument[];
    skipped: StorageImportSkippedFile[];
}

/** 400 body of `POST documents/source-collection/{id}/from-storage/`. */
export interface ImportFromStorageErrorResponse {
    error: string;
    skipped?: StorageImportSkippedFile[];
}

/** The part of a storage item the knowledge import needs; structurally matches files' `StorageItem`. */
export interface StorageImportCandidate {
    id?: number | null;
    name: string;
    type: 'file' | 'folder';
    size?: number;
}

export type FileType = (typeof FILE_TYPES)[number];

export interface CollectionDocument {
    document_id: number;
    file_name: string;
    file_size: number;
    file_type: FileType;
    source_collection: number;
}

export interface DisplayedListDocument {
    document_id?: number;
    file_name: string;
    file_size: number;
    file_type?: string;
    source_collection: number;
    isValidType: boolean;
    isValidSize: boolean;
}

export interface DeleteDocumentResponse {
    message: string;
    document_id: number;
    file_name: string;
}
