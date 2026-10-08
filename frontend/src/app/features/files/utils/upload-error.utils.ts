import { HttpErrorResponse } from '@angular/common/http';
import { formatFileSize } from '@shared/utils';

import { UploadFailure } from '../models/storage.models';

/** Error `code` values of the streaming-upload endpoint. */
export const UploadErrorCode = {
    QuotaExceeded: 'storage_quota_exceeded',
    TooLarge: 'upload_too_large',
    OrgLimitReached: 'org_upload_limit_reached',
    SlotsBusy: 'upload_slots_busy',
    StorageUnavailable: 'storage_unavailable',
    IdleTimeout: 'upload_idle_timeout',
    DurationExceeded: 'upload_duration_exceeded',
    PathIsFile: 'storage_path_is_file',
    OverwriteNotPermitted: 'overwrite_not_permitted',
} as const;

/** A batch file not sent because an earlier file hit a stop condition. */
export class UploadSkippedError extends Error {
    constructor(readonly reason: unknown) {
        super('Upload skipped');
        this.name = 'UploadSkippedError';
    }
}

/** A batch file not sent because it exceeds the backend's size cap. */
export class FileTooLargeError extends Error {
    constructor(readonly limitBytes: number) {
        super('File too large');
        this.name = 'FileTooLargeError';
    }
}

export interface UploadErrorDescription {
    /** Short text for a per-file badge. */
    label: string;
    /** Full sentence for a toast or tooltip. */
    message: string;
    /** False when re-sending the same file cannot succeed. */
    canRetry: boolean;
}

const RESTRICTED_ARCHIVE_PATTERN = /contains (?:executable|(?:password-)?protected) files/;

const QUOTA_EXCEEDED: UploadErrorDescription = {
    label: 'Quota exceeded',
    message: 'Storage quota exceeded for this organization. Free up space and try again.',
    canRetry: false,
};
const TOO_LARGE: UploadErrorDescription = {
    label: 'Too large',
    message: 'The file is larger than the maximum upload size.',
    canRetry: false,
};
const SERVER_BUSY: UploadErrorDescription = {
    label: 'Server busy',
    message: 'The server is busy with other uploads. Please try again in a moment.',
    canRetry: true,
};
const STORAGE_UNAVAILABLE: UploadErrorDescription = {
    label: 'Storage unavailable',
    message: 'File storage is temporarily unavailable. Please try again later.',
    canRetry: true,
};
const TIMED_OUT: UploadErrorDescription = {
    label: 'Timed out',
    message: 'The upload timed out before it finished. Please try again.',
    canRetry: true,
};
const PATH_IS_FILE: UploadErrorDescription = {
    label: 'Folder is a file',
    message:
        'A file has the name of the target folder or of one of its parent folders. Rename it or choose another folder.',
    canRetry: false,
};
const OVERWRITE_NOT_PERMITTED: UploadErrorDescription = {
    label: 'Cannot replace',
    message: 'A file with this name already exists; replacing it requires permission to edit files.',
    canRetry: false,
};
const NOT_ALLOWED: UploadErrorDescription = {
    label: 'Not allowed',
    message: 'You do not have permission to upload files here.',
    canRetry: false,
};
const INTERRUPTED: UploadErrorDescription = {
    label: 'Interrupted',
    message: 'Upload was interrupted by the server (storage quota, size limit or connection).',
    canRetry: true,
};
const SKIPPED: UploadErrorDescription = {
    label: 'Not uploaded',
    message: 'Not uploaded: the storage quota was exceeded by an earlier file.',
    canRetry: true,
};
const UNKNOWN_FAILURE: UploadErrorDescription = {
    label: 'Upload failed',
    message: 'Failed to upload the file.',
    canRetry: true,
};

const DESCRIPTION_BY_CODE: Record<string, UploadErrorDescription> = {
    [UploadErrorCode.QuotaExceeded]: QUOTA_EXCEEDED,
    [UploadErrorCode.TooLarge]: TOO_LARGE,
    [UploadErrorCode.OrgLimitReached]: SERVER_BUSY,
    [UploadErrorCode.SlotsBusy]: SERVER_BUSY,
    [UploadErrorCode.StorageUnavailable]: STORAGE_UNAVAILABLE,
    [UploadErrorCode.IdleTimeout]: TIMED_OUT,
    [UploadErrorCode.DurationExceeded]: TIMED_OUT,
    [UploadErrorCode.PathIsFile]: PATH_IS_FILE,
    [UploadErrorCode.OverwriteNotPermitted]: OVERWRITE_NOT_PERMITTED,
};

/** Fallback descriptions for errors without a known `code` (e.g. from a proxy). */
const DESCRIPTION_BY_STATUS: Record<number, UploadErrorDescription> = {
    401: NOT_ALLOWED,
    403: NOT_ALLOWED,
    408: TIMED_OUT,
    413: TOO_LARGE,
    429: SERVER_BUSY,
    503: SERVER_BUSY,
};

export function getUploadErrorCode(error: unknown): string | null {
    if (!(error instanceof HttpErrorResponse)) return null;
    const body: unknown = error.error;
    if (body && typeof body === 'object' && 'code' in body && typeof body.code === 'string') {
        return body.code;
    }
    return null;
}

/** The envelope's `message` (DRF's `detail` as a fallback); '' for a non-JSON body. */
function getServerMessage(error: HttpErrorResponse): string {
    const body: unknown = error.error;
    if (!body || typeof body !== 'object') return '';
    for (const key of ['message', 'detail'] as const) {
        const value: unknown = key in body ? (body as Record<string, unknown>)[key] : undefined;
        if (typeof value === 'string' && value.trim()) return value.trim();
    }
    return '';
}

export function isStorageQuotaExceeded(error: unknown): boolean {
    return getUploadErrorCode(error) === UploadErrorCode.QuotaExceeded;
}

/** Maps a file's upload error to a user-facing description. */
export function describeUploadError(error: unknown): UploadErrorDescription {
    if (error instanceof UploadSkippedError) return SKIPPED;
    if (error instanceof FileTooLargeError) {
        return {
            ...TOO_LARGE,
            message: `The file is larger than the maximum upload size (max ${formatFileSize(error.limitBytes, 'auto')}).`,
        };
    }
    if (!(error instanceof HttpErrorResponse)) return UNKNOWN_FAILURE;
    // Status 0 here usually means the server rejected the body mid-send (quota, size limit).
    if (error.status === 0) return INTERRUPTED;

    const code = getUploadErrorCode(error);
    const byCode = code ? DESCRIPTION_BY_CODE[code] : undefined;
    if (byCode) return byCode;

    const serverMessage = getServerMessage(error);
    if (error.status === 400) {
        return {
            label: RESTRICTED_ARCHIVE_PATTERN.test(serverMessage) ? 'Contains restricted files' : 'Rejected',
            message: serverMessage || 'The server rejected the file.',
            canRetry: false,
        };
    }
    const byStatus = DESCRIPTION_BY_STATUS[error.status];
    if (byStatus) return byStatus;
    if (error.status >= 500) {
        return {
            label: 'Server error',
            message: serverMessage ? `Unexpected server error: ${serverMessage}` : 'Unexpected server error.',
            canRetry: true,
        };
    }
    return { ...UNKNOWN_FAILURE, message: serverMessage || UNKNOWN_FAILURE.message };
}

/** One toast sentence covering every file of a batch that failed. */
export function describeUploadFailures(failures: UploadFailure[]): string {
    if (!failures.length) return '';
    // Lead with a real failure; a skipped file only echoes one.
    const leading = failures.find((failure) => !(failure.error instanceof UploadSkippedError)) ?? failures[0];
    const message = describeUploadError(leading.error).message;
    if (failures.length === 1) return `Failed to upload "${leading.file.name}". ${message}`;
    return `${failures.length} files were not uploaded. ${message}`;
}
