import { formatFileSize } from '@shared/utils';

import { StorageUploadLimits } from '../models/storage.models';

/** The limits the client can check against, or null when the response can't be relied on:
 *  no response, or an older backend that doesn't say which names are archives. Guessing
 *  would reject files the backend accepts, so without the lists nothing is checked. */
export function usableUploadLimits(limits: StorageUploadLimits | null | undefined): StorageUploadLimits | null {
    if (!limits || !Array.isArray(limits.archive_suffixes) || !Array.isArray(limits.document_extensions)) {
        return null;
    }
    return limits;
}

/** Mirrors the backend's is_archive_name: an archive suffix, and not a document extension
 *  (so "report.docx" is a file even though .docx is a zip underneath). For size checks only:
 *  the backend sends archives to extraction and caps them with max_archive_size. */
export function isArchiveForLimits(fileName: string, limits: StorageUploadLimits): boolean {
    const lower = fileName.toLowerCase();
    if (limits.document_extensions.some((extension) => lower.endsWith(extension))) return false;
    return limits.archive_suffixes.some((suffix) => lower.endsWith(suffix));
}

/** The size cap that applies to a file of this name, or null when it is not capped. */
export function uploadLimitFor(fileName: string, limits: StorageUploadLimits): number | null {
    return isArchiveForLimits(fileName, limits) ? limits.max_archive_size : limits.max_file_size;
}

/** One line for the file-selection UI (sizes as in the dialogs' file lists), or null when the limits are unknown. */
export function describeUploadLimits(limits: StorageUploadLimits | null): string | null {
    const usable = usableUploadLimits(limits);
    if (!usable) return null;
    const parts: string[] = [];
    if (usable.max_file_size !== null) parts.push(`Max file size: ${formatFileSize(usable.max_file_size, 'auto')}`);
    parts.push(`Max archive size: ${formatFileSize(usable.max_archive_size, 'auto')}`);
    return parts.join(' · ');
}
