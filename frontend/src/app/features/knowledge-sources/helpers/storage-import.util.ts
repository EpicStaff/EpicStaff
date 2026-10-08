import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { FILE_TYPES, MAX_DOCUMENT_SIZE } from '../constants/constants';
import {
    ImportFromStorageResponse,
    StorageImportCandidate,
    StorageImportSkippedFile,
    StorageImportSkipReason,
} from '../models/document.model';

const SKIP_REASON_LABELS: Record<StorageImportSkipReason, string> = {
    unsupported_type: 'unsupported type',
    too_large: 'too large',
    duplicate: 'already in the collection',
};

export interface StorageImportSummary {
    kind: 'success' | 'warning';
    message: string;
}

/**
 * Mirrors the backend gate of `POST documents/source-collection/{id}/from-storage/`
 * (KnowledgeSources CREATE + Files READ), plus KnowledgeSources READ to list the collections.
 */
export function canImportStorageToKnowledge(permissions: PermissionsService): boolean {
    return (
        permissions.can(ResourceCode.KnowledgeSources, ActionCode.Create) &&
        permissions.can(ResourceCode.KnowledgeSources, ActionCode.Read) &&
        permissions.can(ResourceCode.Files, ActionCode.Read)
    );
}

/**
 * The storage ids to send, exactly as dragged/selected (the server expands folders).
 * `storage/list/` builds every item from a StorageFile row, so a missing id is not expected
 * there; only `storage/tree/` synthesises id-less intermediate folders.
 */
export function extractStorageFileIds(items: StorageImportCandidate[]): {
    storageFileIds: number[];
    missingCount: number;
} {
    const storageFileIds = items.map((item) => item.id).filter((id): id is number => typeof id === 'number');
    return { storageFileIds, missingCount: items.length - storageFileIds.length };
}

/** "2 unsupported type, 1 too large" — grouped in a stable reason order. */
export function formatSkippedReasons(skipped: StorageImportSkippedFile[]): string {
    const counts = new Map<StorageImportSkipReason, number>();
    for (const file of skipped) {
        counts.set(file.reason, (counts.get(file.reason) ?? 0) + 1);
    }
    return (Object.keys(SKIP_REASON_LABELS) as StorageImportSkipReason[])
        .filter((reason) => counts.has(reason))
        .map((reason) => `${counts.get(reason)} ${SKIP_REASON_LABELS[reason]}`)
        .join(', ');
}

export function buildStorageImportSummary(response: ImportFromStorageResponse): StorageImportSummary {
    const importedCount = response.documents.length;
    const skipped = response.skipped ?? [];
    const imported = `${importedCount} document${importedCount === 1 ? '' : 's'} imported`;
    const skippedPart = skipped.length ? `, ${skipped.length} skipped (${formatSkippedReasons(skipped)})` : '';
    const kind = importedCount > 0 && skipped.length === 0 ? 'success' : 'warning';
    return { kind, message: `${imported}${skippedPart}` };
}

/**
 * Client-side guess only: `FILE_TYPES` and `MAX_DOCUMENT_SIZE` duplicate the server rules
 * by hand, and folders are expanded on the server. The server response is authoritative.
 */
export function isLikelyUnsupportedDocument(candidate: StorageImportCandidate): boolean {
    if (candidate.type !== 'file') return false;
    const dotIndex = candidate.name.lastIndexOf('.');
    const extension = dotIndex > 0 ? candidate.name.slice(dotIndex + 1).toLowerCase() : '';
    const isSupportedType = FILE_TYPES.includes(extension);
    const isTooLarge = (candidate.size ?? 0) >= MAX_DOCUMENT_SIZE;
    return !isSupportedType || isTooLarge;
}
