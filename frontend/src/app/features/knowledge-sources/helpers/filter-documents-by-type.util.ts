import { DisplayedListDocument } from '../models/document.model';
import { isStoredDocument } from './collection-stats.util';

/**
 * The documents to display for the "Filter by type" choice; `null` means all types.
 *
 * Only stored documents are filtered. Uploads in flight and rejected dropped files stay visible under any
 * filter, so their progress and validation errors are never hidden.
 */
export function filterDocumentsByType<T extends Pick<DisplayedListDocument, 'document_id' | 'file_type'>>(
    documents: T[],
    fileType: string | null
): T[] {
    if (!fileType) return documents;
    return documents.filter((document) => !isStoredDocument(document) || document.file_type === fileType);
}
