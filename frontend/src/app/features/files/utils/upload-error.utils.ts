import { HttpErrorResponse } from '@angular/common/http';
import { formatFileSize } from '@shared/utils';

import { UploadFailure } from '../models/storage.models';

/** `code` values the streaming-upload endpoint puts in its `{status_code, code, message}` envelope. */
export const UploadErrorCode = {
    QuotaExceeded: 'storage_quota_exceeded',
    TooLarge: 'upload_too_large',
    OrgLimitReached: 'org_upload_limit_reached',
    SlotsBusy: 'upload_slots_busy',
    StorageUnavailable: 'storage_unavailable',
    IdleTimeout: 'upload_idle_timeout',
    DurationExceeded: 'upload_duration_exceeded',
} as const;

/** A file of a batch that was never sent, because an earlier file hit a stop condition. */
export class UploadSkippedError extends Error {
    constructor(readonly reason: unknown) {
        super('Upload skipped');
        this.name = 'UploadSkippedError';
    }
}

/** A file of a batch that was never sent, because it is larger than the backend accepts. */
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
    /** False when sending the same file again cannot succeed (the user has to change something first). */
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
};

/** For answers without a known `code` (e.g. a proxy in front of Django answered). */
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

/** Maps the error one uploaded file failed with to what the user should read. */
export function describeUploadError(error: unknown): UploadErrorDescription {
    if (error instanceof UploadSkippedError) return SKIPPED;
    if (error instanceof FileTooLargeError) {
        return {
            ...TOO_LARGE,
            message: `The file is larger than the maximum upload size (max ${formatFileSize(error.limitBytes, 'auto')}).`,
        };
    }
    if (!(error instanceof HttpErrorResponse)) return UNKNOWN_FAILURE;
    // Status 0 on this endpoint almost always means the server rejected the body
    // while it was still being sent (quota, size limit), so the browser saw no answer.
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

/** One sentence for a toast about every file of a batch that did not upload. */
export function describeUploadFailures(failures: UploadFailure[]): string {
    if (!failures.length) return '';
    // A skipped file only echoes another failure; lead with the failure that caused it.
    const leading = failures.find((failure) => !(failure.error instanceof UploadSkippedError)) ?? failures[0];
    const message = describeUploadError(leading.error).message;
    if (failures.length === 1) return `Failed to upload "${leading.file.name}". ${message}`;
    return `${failures.length} files were not uploaded. ${message}`;
}
