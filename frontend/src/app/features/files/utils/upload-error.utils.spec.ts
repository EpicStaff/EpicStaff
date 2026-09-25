import { HttpErrorResponse } from '@angular/common/http';

import {
    describeUploadError,
    describeUploadFailures,
    FileTooLargeError,
    isStorageQuotaExceeded,
    UploadSkippedError,
} from './upload-error.utils';

function httpError(status: number, body: unknown = null): HttpErrorResponse {
    return new HttpErrorResponse({ status, error: body, url: '/api/storage/upload/stream?filename=a.txt' });
}

function envelope(status: number, code: string, message: string): HttpErrorResponse {
    return httpError(status, { status_code: status, code, message });
}

describe('describeUploadError', () => {
    it.each([
        { status: 413, code: 'storage_quota_exceeded', label: 'Quota exceeded', canRetry: false },
        { status: 413, code: 'upload_too_large', label: 'Too large', canRetry: false },
        { status: 429, code: 'org_upload_limit_reached', label: 'Server busy', canRetry: true },
        { status: 503, code: 'upload_slots_busy', label: 'Server busy', canRetry: true },
        { status: 503, code: 'storage_unavailable', label: 'Storage unavailable', canRetry: true },
        { status: 408, code: 'upload_idle_timeout', label: 'Timed out', canRetry: true },
        { status: 408, code: 'upload_duration_exceeded', label: 'Timed out', canRetry: true },
    ])('maps $code to "$label"', ({ status, code, label, canRetry }) => {
        const description = describeUploadError(envelope(status, code, 'server text'));
        expect(description.label).toBe(label);
        expect(description.canRetry).toBe(canRetry);
        expect(description.message).not.toBe('');
    });

    it('explains a status 0 as an interruption, not as being offline', () => {
        // The network interceptor rewrites the body of every status-0 error to an "offline" text.
        const offlineRewritten = httpError(0, { message: 'You appear to be offline.' });
        expect(describeUploadError(offlineRewritten).message).toBe(
            'Upload was interrupted by the server (storage quota, size limit or connection).'
        );
    });

    it('marks restricted archive contents and uses the server reason as the message', () => {
        const reason = "Archive 'a.zip' contains executable files: run.exe";
        const description = describeUploadError(envelope(400, 'invalid', reason));
        expect(description).toEqual({ label: 'Contains restricted files', message: reason, canRetry: false });
    });

    it('shows other 400 reasons as rejected', () => {
        const description = describeUploadError(envelope(400, 'invalid', "Archive 'a.zip' is empty"));
        expect(description.label).toBe('Rejected');
        expect(description.message).toBe("Archive 'a.zip' is empty");
    });

    it('includes the envelope message for an unexpected 500', () => {
        const description = describeUploadError(envelope(500, 'RuntimeError', 'Unpredictable error'));
        expect(description.label).toBe('Server error');
        expect(description.message).toBe('Unexpected server error: Unpredictable error');
    });

    it('falls back on the status when the body has no known code (e.g. a proxy answered)', () => {
        expect(describeUploadError(httpError(413, '<html>Request Entity Too Large</html>')).label).toBe('Too large');
        expect(describeUploadError(httpError(504, null)).message).toBe('Unexpected server error.');
        expect(describeUploadError(httpError(403, { detail: 'nope' })).label).toBe('Not allowed');
    });

    it('describes a skipped file and a non-HTTP error', () => {
        expect(describeUploadError(new UploadSkippedError(null)).label).toBe('Not uploaded');
        expect(describeUploadError(new Error('boom')).label).toBe('Upload failed');
    });
});

describe('describeUploadError for a file too large to send', () => {
    it('is final and names the limit as the file lists size files', () => {
        const description = describeUploadError(new FileTooLargeError(2 * 1024 ** 3));
        expect(description.label).toBe('Too large');
        expect(description.message).toBe('The file is larger than the maximum upload size (max 2.0 GB).');
        expect(description.canRetry).toBe(false);
    });
});

describe('isStorageQuotaExceeded', () => {
    it('is true only for the quota code', () => {
        expect(isStorageQuotaExceeded(envelope(413, 'storage_quota_exceeded', 'x'))).toBe(true);
        expect(isStorageQuotaExceeded(envelope(413, 'upload_too_large', 'x'))).toBe(false);
        expect(isStorageQuotaExceeded(new Error('x'))).toBe(false);
    });
});

describe('describeUploadFailures', () => {
    const file = (name: string): File => new File(['x'], name);

    it('names the file when only one failed', () => {
        const message = describeUploadFailures([
            { file: file('a.txt'), error: envelope(413, 'upload_too_large', 'x') },
        ]);
        expect(message).toBe('Failed to upload "a.txt". The file is larger than the maximum upload size.');
    });

    it('counts the failures and leads with the cause rather than a skipped file', () => {
        const quota = envelope(413, 'storage_quota_exceeded', 'x');
        const message = describeUploadFailures([
            { file: file('b.txt'), error: new UploadSkippedError(quota) },
            { file: file('a.txt'), error: quota },
        ]);
        expect(message).toBe(
            '2 files were not uploaded. Storage quota exceeded for this organization. Free up space and try again.'
        );
    });

    it('uses the size limit for a file that was never sent', () => {
        const message = describeUploadFailures([
            { file: file('big.zip'), error: new FileTooLargeError(50 * 1024 * 1024) },
        ]);
        expect(message).toBe(
            'Failed to upload "big.zip". The file is larger than the maximum upload size (max 50.0 MB).'
        );
    });

    it('is empty with no failures', () => {
        expect(describeUploadFailures([])).toBe('');
    });
});
