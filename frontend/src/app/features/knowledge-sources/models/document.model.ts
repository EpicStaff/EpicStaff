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

/** `code` of the 400 sent when every selected storage file was skipped. */
export const NOTHING_TO_IMPORT_ERROR_CODE = 'nothing_to_import';

/** 4xx body of `POST documents/source-collection/{id}/from-storage/` — the project error envelope. */
export interface ImportFromStorageErrorResponse {
    status_code: number;
    code: string;
    message: string;
    /** Sent only with `NOTHING_TO_IMPORT_ERROR_CODE`: every selected file and why it was skipped. */
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

/** Which documents an edit reaches when other collections use the same file. */
export type DocumentContentScope = 'this_collection' | 'all_collections';

export interface SharedCollection {
    collection_id: number;
    collection_name: string;
}

export interface DocumentDetail extends CollectionDocument {
    collection_name: string;
    /** The version an edit sends back, so a save from an older text is refused; null for a document without content. */
    content_hash: string | null;
    /** Other collections whose documents use the same file. */
    shared_with_collections: SharedCollection[];
}

/** A text document with its current text; `content_hash` is the hash of exactly this text. */
export interface DocumentText extends DocumentDetail {
    /** Always set: a document without content cannot be read for editing. */
    content_hash: string;
    text: string;
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
