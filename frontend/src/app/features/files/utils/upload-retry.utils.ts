import { HttpErrorResponse } from '@angular/common/http';
import { getRetryAfterSeconds } from '@shared/utils';

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
    const seconds = getRetryAfterSeconds(error) ?? fallback;
    return Math.min(seconds, UPLOAD_RETRY_MAX_SECONDS) * 1000;
}
