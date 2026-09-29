import { formatFileSize } from '@shared/utils';

import { StorageUploadLimits } from '../models/storage.models';

/** Returns the limits if they can be checked against, else null.
 *  Without the archive lists nothing is checked: guessing would reject files the backend accepts. */
export function usableUploadLimits(limits: StorageUploadLimits | null | undefined): StorageUploadLimits | null {
    if (!limits || !Array.isArray(limits.archive_suffixes) || !Array.isArray(limits.document_extensions)) {
        return null;
    }
    return limits;
}

/** Mirrors the backend's is_archive_name: an archive suffix and not a document extension (".docx"). */
export function isArchiveForLimits(fileName: string, limits: StorageUploadLimits): boolean {
    const lower = fileName.toLowerCase();
    if (limits.document_extensions.some((extension) => lower.endsWith(extension))) return false;
    return limits.archive_suffixes.some((suffix) => lower.endsWith(suffix));
}

/** The size cap that applies to a file of this name, or null when it is not capped. */
export function uploadLimitFor(fileName: string, limits: StorageUploadLimits): number | null {
    return isArchiveForLimits(fileName, limits) ? limits.max_archive_size : limits.max_file_size;
}

/** One-line size-cap hint for the file-selection UI, or null when the limits are unknown. */
export function describeUploadLimits(limits: StorageUploadLimits | null): string | null {
    const usable = usableUploadLimits(limits);
    if (!usable) return null;
    const parts: string[] = [];
    if (usable.max_file_size !== null) parts.push(`Max file size: ${formatFileSize(usable.max_file_size, 'auto')}`);
    parts.push(`Max archive size: ${formatFileSize(usable.max_archive_size, 'auto')}`);
    return parts.join(' · ');
}
