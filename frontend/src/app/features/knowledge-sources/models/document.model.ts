import { FILE_TYPES } from '../constants/constants';

export interface UploadDocumentResponse {
    message: string;
    documents: CollectionDocument[];
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
