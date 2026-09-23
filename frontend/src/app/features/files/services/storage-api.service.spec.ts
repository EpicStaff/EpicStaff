import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';

import { ConfigService } from '../../../services/config';
import { StorageStreamUploadResponse, StorageUploadLimits } from '../models/storage.models';
import {
    STORAGE_UNAVAILABLE_RETRY_FALLBACK_SECONDS,
    StorageApiService,
    UPLOAD_MAX_ATTEMPTS,
    UPLOAD_RETRY_FALLBACK_SECONDS,
} from './storage-api.service';

const STREAM_URL = '/api/storage/upload/stream';
const LIMITS_URL = '/api/storage/upload-limits/';

function makeFile(name: string): File {
    return new File(['content'], name, { type: 'text/plain' });
}

function errorEnvelope(status: number, code: string, message = 'error'): object {
    return { status_code: status, code, message };
}

describe('StorageApiService', () => {
    let service: StorageApiService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: ConfirmationDialogService, useValue: {} as unknown as ConfirmationDialogService },
            ],
        });
        service = TestBed.inject(StorageApiService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        httpMock.verify();
        vi.useRealTimers();
    });

    /** Takes every stream upload request currently open (each is returned only once). */
    function takeStreamRequests(): TestRequest[] {
        return httpMock.match((request) => request.url.startsWith(STREAM_URL));
    }

    function succeed(request: TestRequest): void {
        request.flush({ status: 'DONE', path: (request.request.body as File).name, size: 7 });
    }

    /** Starts one upload and records how it ended. */
    function startUpload(name = 'a.txt'): {
        response: () => StorageStreamUploadResponse | undefined;
        error: () => unknown;
    } {
        let response: StorageStreamUploadResponse | undefined;
        let error: unknown;
        service.uploadStream('', makeFile(name)).subscribe({
            next: (value) => (response = value),
            error: (value: unknown) => (error = value),
        });
        return { response: () => response, error: () => error };
    }

    describe('getUploadLimits', () => {
        it('returns the limits response', () => {
            const limits: StorageUploadLimits = {
                max_file_size: 10,
                max_archive_size: 5,
                free_bytes: 100,
                archive_suffixes: ['.zip'],
                document_extensions: ['.docx'],
            };
            let received: StorageUploadLimits | null | undefined;
            service.getUploadLimits().subscribe((value) => (received = value));

            const request = httpMock.expectOne(LIMITS_URL);
            expect(request.request.method).toBe('GET');
            request.flush(limits);
            expect(received).toEqual(limits);
        });
    });

    describe('uploadStream', () => {
        it('streams the File itself as the body and escapes "+" in the name', () => {
            service.uploadStream('docs/', makeFile('a+b.txt')).subscribe();

            const [request] = takeStreamRequests();
            expect(request.request.url).toBe(`${STREAM_URL}?filename=a%2Bb.txt&path=docs`);
            expect(request.request.body).toBeInstanceOf(File);
            expect(request.request.headers.get('Content-Type')).toBe('application/octet-stream');
            succeed(request);
        });

        it('retries a 429 after the Retry-After delay', () => {
            vi.useFakeTimers();
            const upload = startUpload();

            takeStreamRequests()[0].flush(errorEnvelope(429, 'org_upload_limit_reached'), {
                status: 429,
                statusText: 'Too Many Requests',
                headers: { 'Retry-After': '2' },
            });

            vi.advanceTimersByTime(1999);
            expect(takeStreamRequests().length).toBe(0);
            vi.advanceTimersByTime(1);
            const retried = takeStreamRequests();
            expect(retried.length).toBe(1);
            succeed(retried[0]);

            expect(upload.response()?.path).toBe('a.txt');
        });

        it('retries a 503 after the Retry-After delay', () => {
            vi.useFakeTimers();
            const upload = startUpload();

            takeStreamRequests()[0].flush(errorEnvelope(503, 'upload_slots_busy'), {
                status: 503,
                statusText: 'Service Unavailable',
                headers: { 'Retry-After': '3' },
            });

            vi.advanceTimersByTime(2999);
            expect(takeStreamRequests().length).toBe(0);
            vi.advanceTimersByTime(1);
            succeed(takeStreamRequests()[0]);

            expect(upload.response()).toBeDefined();
        });

        it('reads a Retry-After given as an HTTP date', () => {
            vi.useFakeTimers();
            const now = Date.UTC(2026, 0, 1, 12, 0, 0);
            vi.setSystemTime(now);
            const upload = startUpload();

            takeStreamRequests()[0].flush(errorEnvelope(429, 'org_upload_limit_reached'), {
                status: 429,
                statusText: 'Too Many Requests',
                headers: { 'Retry-After': new Date(now + 4000).toUTCString() },
            });

            vi.advanceTimersByTime(3999);
            expect(takeStreamRequests().length).toBe(0);
            vi.advanceTimersByTime(1);
            succeed(takeStreamRequests()[0]);

            expect(upload.response()).toBeDefined();
        });

        it('retries at once when the Retry-After date is already past', () => {
            vi.useFakeTimers();
            const now = Date.UTC(2026, 0, 1, 12, 0, 0);
            vi.setSystemTime(now);
            startUpload();

            takeStreamRequests()[0].flush(errorEnvelope(503, 'upload_slots_busy'), {
                status: 503,
                statusText: 'Service Unavailable',
                headers: { 'Retry-After': new Date(now - 60_000).toUTCString() },
            });

            vi.advanceTimersByTime(0);
            succeed(takeStreamRequests()[0]);
        });

        it('falls back to a short wait for storage_unavailable and a long one otherwise when Retry-After is missing', () => {
            vi.useFakeTimers();
            startUpload('storage.txt');
            startUpload('busy.txt');
            const [storage, busy] = takeStreamRequests();

            storage.flush(errorEnvelope(503, 'storage_unavailable'), {
                status: 503,
                statusText: 'Service Unavailable',
            });
            busy.flush(errorEnvelope(429, 'org_upload_limit_reached'), {
                status: 429,
                statusText: 'Too Many Requests',
            });

            vi.advanceTimersByTime(STORAGE_UNAVAILABLE_RETRY_FALLBACK_SECONDS * 1000);
            const afterShortWait = takeStreamRequests();
            expect(afterShortWait.map((request) => (request.request.body as File).name)).toEqual(['storage.txt']);
            succeed(afterShortWait[0]);

            vi.advanceTimersByTime((UPLOAD_RETRY_FALLBACK_SECONDS - STORAGE_UNAVAILABLE_RETRY_FALLBACK_SECONDS) * 1000);
            const afterLongWait = takeStreamRequests();
            expect(afterLongWait.map((request) => (request.request.body as File).name)).toEqual(['busy.txt']);
            succeed(afterLongWait[0]);
        });

        it('gives up after UPLOAD_MAX_ATTEMPTS and errors with the last response', () => {
            vi.useFakeTimers();
            const upload = startUpload();

            for (let attempt = 1; attempt <= UPLOAD_MAX_ATTEMPTS; attempt++) {
                const requests = takeStreamRequests();
                expect(requests.length).toBe(1);
                requests[0].flush(errorEnvelope(503, 'upload_slots_busy'), {
                    status: 503,
                    statusText: 'Service Unavailable',
                    headers: { 'Retry-After': '1' },
                });
                vi.advanceTimersByTime(1000);
            }

            expect(takeStreamRequests().length).toBe(0);
            expect(upload.error()).toMatchObject({ status: 503 });
        });

        it.each([
            { status: 413, code: 'upload_too_large' },
            { status: 408, code: 'upload_idle_timeout' },
            { status: 400, code: 'invalid' },
            { status: 500, code: 'RuntimeError' },
        ])('does not retry a $status ($code)', ({ status, code }) => {
            vi.useFakeTimers();
            const upload = startUpload();

            takeStreamRequests()[0].flush(errorEnvelope(status, code), {
                status,
                statusText: 'Error',
                headers: { 'Retry-After': '1' },
            });
            vi.advanceTimersByTime(UPLOAD_RETRY_FALLBACK_SECONDS * 1000);

            expect(takeStreamRequests().length).toBe(0);
            expect(upload.error()).toMatchObject({ status });
        });

        it('does not retry a status 0 (body rejected mid-send or connection lost)', () => {
            vi.useFakeTimers();
            const upload = startUpload();

            takeStreamRequests()[0].error(new ProgressEvent('error'));
            vi.advanceTimersByTime(UPLOAD_RETRY_FALLBACK_SECONDS * 1000);

            expect(takeStreamRequests().length).toBe(0);
            expect(upload.error()).toMatchObject({ status: 0 });
        });
    });
});
