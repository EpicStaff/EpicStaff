import { DisplayedListDocument } from '../models/document.model';

const SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];
const BYTES_PER_UNIT = 1024;

/** Shown for "File types" when the collection has no stored files. */
export const NO_FILE_TYPES = '—';

/** The quantitative parameters and memory capacity of a collection, ready to display. */
export interface CollectionStats {
    fileCount: number;
    /** Distinct extensions of the stored files, alphabetical, without the leading dot. */
    fileTypes: string[];
    totalSize: string;
    largestFileSize: string;
    smallestFileSize: string;
}

export type CollectionStatsDocument = Pick<DisplayedListDocument, 'document_id' | 'file_type' | 'file_size'>;

/**
 * A document the backend has stored. The files list also shows uploads still in flight and dropped files
 * rejected for their type or size; those have no id yet and are not part of the collection.
 */
export function isStoredDocument<T extends Pick<DisplayedListDocument, 'document_id'>>(
    document: T
): document is T & { document_id: number } {
    return document.document_id !== undefined && document.document_id !== null;
}

/** Distinct file types of the stored documents, alphabetical. */
export function collectFileTypes(documents: CollectionStatsDocument[]): string[] {
    const types = new Set<string>();
    for (const document of documents) {
        if (isStoredDocument(document) && document.file_type) types.add(document.file_type);
    }
    return Array.from(types).sort();
}

/** `['pdf', 'txt']` → `.pdf, .txt`. */
export function formatFileTypes(fileTypes: string[]): string {
    return fileTypes.length ? fileTypes.map((type) => `.${type}`).join(', ') : NO_FILE_TYPES;
}

/** `10240` → `10 KB`, `1536` → `1.5 KB`; whole values drop the decimals. */
export function formatCollectionSize(bytes: number): string {
    if (bytes <= 0) return '0 B';
    const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(BYTES_PER_UNIT)), SIZE_UNITS.length - 1);
    const value = bytes / Math.pow(BYTES_PER_UNIT, unitIndex);
    return `${value % 1 === 0 ? value : value.toFixed(1)} ${SIZE_UNITS[unitIndex]}`;
}

/** Stats over the stored documents only — see {@link isStoredDocument}. */
export function buildCollectionStats(documents: CollectionStatsDocument[]): CollectionStats {
    const sizes = documents.filter(isStoredDocument).map((document) => document.file_size ?? 0);
    const hasFiles = sizes.length > 0;
    return {
        fileCount: sizes.length,
        fileTypes: collectFileTypes(documents),
        totalSize: formatCollectionSize(sizes.reduce((total, size) => total + size, 0)),
        largestFileSize: formatCollectionSize(hasFiles ? sizes.reduce((largest, size) => Math.max(largest, size)) : 0),
        smallestFileSize: formatCollectionSize(
            hasFiles ? sizes.reduce((smallest, size) => Math.min(smallest, size)) : 0
        ),
    };
}
