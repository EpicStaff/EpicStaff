import { HttpErrorResponse } from '@angular/common/http';

import { getUploadErrorCode, UploadErrorCode } from './upload-error.utils';

/** Max attempts per file on 429/503, the first one included. */
export const UPLOAD_MAX_ATTEMPTS = 5;
/** Fallback wait when a 429/503 has no readable Retry-After. */
export const UPLOAD_RETRY_FALLBACK_SECONDS = 30;
export const STORAGE_UNAVAILABLE_RETRY_FALLBACK_SECONDS = 5;
/** Upper bound on one wait. */
const UPLOAD_RETRY_MAX_SECONDS = 120;

/** The only statuses where re-sending the same file later can succeed. */
const RETRYABLE_UPLOAD_STATUSES = new Set([429, 503]);

/** Delay before re-sending after `error`, or null when it must not be retried. */
export function uploadRetryDelayMs(error: unknown): number | null {
    if (!(error instanceof HttpErrorResponse) || !RETRYABLE_UPLOAD_STATUSES.has(error.status)) return null;
    const fallback =
        getUploadErrorCode(error) === UploadErrorCode.StorageUnavailable
            ? STORAGE_UNAVAILABLE_RETRY_FALLBACK_SECONDS
            : UPLOAD_RETRY_FALLBACK_SECONDS;
    const seconds = parseRetryAfterSeconds(error.headers.get('Retry-After')) ?? fallback;
    return Math.min(seconds, UPLOAD_RETRY_MAX_SECONDS) * 1000;
}

/** Parses Retry-After, which is delay-seconds or an HTTP date. */
function parseRetryAfterSeconds(header: string | null): number | null {
    if (!header) return null;
    const value = header.trim();
    if (/^\d+$/.test(value)) return Number(value);
    const date = Date.parse(value);
    if (Number.isNaN(date)) return null;
    return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}
