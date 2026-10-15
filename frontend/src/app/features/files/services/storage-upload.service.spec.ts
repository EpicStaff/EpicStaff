import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Subscription } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { ToastService } from '../../../services/notifications';
import { StorageUploadBatchResult, StorageUploadLimits, StorageUploadOutcome } from '../models/storage.models';
import { FileTooLargeError, UploadSkippedError } from '../utils/upload-error.utils';
import { StorageUploadService, UPLOAD_CONCURRENCY } from './storage-upload.service';

const STREAM_URL = '/api/storage/upload/stream';
const LIMITS_URL = '/api/storage/upload-limits/';
const MB = 1024 * 1024;

/** The backend's archive rules (archive_formats.py); every size is effectively uncapped. */
const UNCAPPED: StorageUploadLimits = {
    max_file_size: null,
    max_archive_size: 1024 * 1024 * MB,
    free_bytes: 1024 * 1024 * MB,
    archive_suffixes: ['.tar', '.tar.bz2', '.tar.gz', '.tar.xz', '.taz', '.tbz', '.tbz2', '.tgz', '.txz', '.zip'],
    document_extensions: ['.docx', '.epub', '.jar', '.odt', '.xlsx'],
};

/** `size` overrides the real 7-byte body, so a "500 MB" file costs nothing to build. */
function makeFile(name: string, size?: number): File {
    const file = new File(['content'], name, { type: 'text/plain' });
    if (size !== undefined) Object.defineProperty(file, 'size', { value: size });
    return file;
}

function errorEnvelope(status: number, code: string, message = 'error'): object {
    return { status_code: status, code, message };
}

describe('StorageUploadService', () => {
    let service: StorageUploadService;
    let httpMock: HttpTestingController;
    let toastWarning: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        toastWarning = vi.fn();
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: ConfirmationDialogService, useValue: {} as unknown as ConfirmationDialogService },
                { provide: ToastService, useValue: { warning: toastWarning } as unknown as ToastService },
            ],
        });
        service = TestBed.inject(StorageUploadService);
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

    function uploadedFileName(request: TestRequest): string {
        return (request.request.body as File).name;
    }

    function succeed(request: TestRequest): void {
        request.flush({ status: 'DONE', path: uploadedFileName(request), size: 7 });
    }

    function toFiles(files: (string | File)[]): File[] {
        return files.map((file) => (typeof file === 'string' ? makeFile(file) : file));
    }

    /** Starts a batch and answers its limits request (uncapped unless told otherwise). */
    function startBatch(
        files: (string | File)[],
        limits: StorageUploadLimits | object = UNCAPPED
    ): { result: () => StorageUploadBatchResult | undefined; subscription: Subscription } {
        const batch = startBatchWithoutLimits(files);
        httpMock.expectOne(LIMITS_URL).flush(limits);
        return batch;
    }

    function startBatchWithoutLimits(files: (string | File)[]): {
        result: () => StorageUploadBatchResult | undefined;
        subscription: Subscription;
    } {
        let result: StorageUploadBatchResult | undefined;
        const subscription = service.uploadMany('', toFiles(files)).subscribe({
            next: (batch) => (result = batch),
            error: () => {
                throw new Error('uploadMany must never error');
            },
        });
        return { result: () => result, subscription };
    }

    function failedNames(result: StorageUploadBatchResult | undefined): string[] {
        return (result?.failed ?? []).map((failure) => failure.file.name).sort();
    }

    function uploadedNames(result: StorageUploadBatchResult | undefined): string[] {
        return (result?.uploaded ?? []).map((uploaded) => uploaded.file.name).sort();
    }

    describe('size pre-flight', () => {
        it('does not request limits or upload anything for an empty batch', () => {
            let result: StorageUploadBatchResult | undefined;
            service.uploadMany('', []).subscribe((batch) => (result = batch));
            expect(result).toEqual({ uploaded: [], failed: [] });
        });

        it('reports a flat file over max_file_size without sending it and uploads its siblings', () => {
            const limits: StorageUploadLimits = { ...UNCAPPED, max_file_size: 500 * MB };
            const batch = startBatch([makeFile('big.pdf', 500 * MB + 1), 'a.txt', 'b.txt'], limits);

            const requests = takeStreamRequests();
            expect(requests.map(uploadedFileName)).toEqual(['a.txt', 'b.txt']);
            requests.forEach(succeed);

            const result = batch.result();
            expect(uploadedNames(result)).toEqual(['a.txt', 'b.txt']);
            expect(failedNames(result)).toEqual(['big.pdf']);
            const error = result?.failed[0].error;
            expect(error).toBeInstanceOf(FileTooLargeError);
            expect((error as FileTooLargeError).limitBytes).toBe(500 * MB);
        });

        it('sends a file exactly at the limit', () => {
            const batch = startBatch([makeFile('edge.pdf', 500 * MB)], { ...UNCAPPED, max_file_size: 500 * MB });
            succeed(takeStreamRequests()[0]);
            expect(uploadedNames(batch.result())).toEqual(['edge.pdf']);
        });

        it('checks names the backend unpacks against max_archive_size and the rest against max_file_size', () => {
            const limits: StorageUploadLimits = { ...UNCAPPED, max_file_size: 500 * MB, max_archive_size: 50 * MB };
            const batch = startBatch(
                [
                    makeFile('bundle.ZIP', 62 * MB),
                    makeFile('bundle.tar.gz', 62 * MB),
                    makeFile('logs.txz', 62 * MB),
                    makeFile('old.TBZ2', 62 * MB),
                    makeFile('passwords.txt.gz', 62 * MB),
                    makeFile('dump.sql.gz', 62 * MB),
                    makeFile('report.docx', 62 * MB),
                ],
                limits
            );

            const requests = takeStreamRequests();
            // A bare .gz is stored as it is, not unpacked, so the file cap applies to it.
            expect(requests.map(uploadedFileName)).toEqual(['passwords.txt.gz', 'dump.sql.gz', 'report.docx']);
            requests.forEach(succeed);

            const result = batch.result();
            expect(failedNames(result)).toEqual(['bundle.ZIP', 'bundle.tar.gz', 'logs.txz', 'old.TBZ2']);
            for (const failure of result?.failed ?? []) {
                expect((failure.error as FileTooLargeError).limitBytes).toBe(50 * MB);
            }
        });

        it('sends every plain file when max_file_size is null', () => {
            const batch = startBatch([makeFile('video.mp4', 900 * MB)], { ...UNCAPPED, max_file_size: null });
            succeed(takeStreamRequests()[0]);
            expect(batch.result()?.failed).toEqual([]);
        });

        it.each([
            { label: 'no archive lists', limits: { max_file_size: 1, max_archive_size: 1, free_bytes: 1 } },
            {
                label: 'no document list',
                limits: { max_file_size: 1, max_archive_size: 1, free_bytes: 1, archive_suffixes: ['.zip'] },
            },
            { label: 'a null body (no Files/Read)', limits: null },
        ])('checks nothing and does not warn when the limits have $label', ({ limits }) => {
            const batch = startBatchWithoutLimits([makeFile('huge.zip', 10 * 1024 * MB), makeFile('big.pdf', 5 * MB)]);
            httpMock.expectOne(LIMITS_URL).flush(limits);

            const requests = takeStreamRequests();
            expect(requests.map(uploadedFileName)).toEqual(['huge.zip', 'big.pdf']);
            requests.forEach(succeed);
            expect(batch.result()?.uploaded.length).toBe(2);
            expect(toastWarning).not.toHaveBeenCalled();
        });

        it.each([
            {
                label: 'a 500',
                fail: (request: TestRequest) => request.flush(null, { status: 500, statusText: 'Error' }),
            },
            { label: 'a status 0', fail: (request: TestRequest) => request.error(new ProgressEvent('error')) },
        ])('uploads every file unchecked when the limits request fails with $label', ({ fail }) => {
            const batch = startBatchWithoutLimits([makeFile('huge.zip', 10 * 1024 * MB), 'a.txt']);
            fail(httpMock.expectOne(LIMITS_URL));

            const requests = takeStreamRequests();
            expect(requests.map(uploadedFileName)).toEqual(['huge.zip', 'a.txt']);
            requests.forEach(succeed);
            expect(batch.result()?.uploaded.length).toBe(2);
            expect(toastWarning).not.toHaveBeenCalled();
        });
    });

    describe('free-space warning', () => {
        it('warns but still sends everything when the files to send exceed free_bytes', () => {
            const limits: StorageUploadLimits = { ...UNCAPPED, free_bytes: 100 * MB };
            const batch = startBatch([makeFile('a.pdf', 60 * MB), makeFile('b.pdf', 60 * MB)], limits);

            expect(toastWarning).toHaveBeenCalledTimes(1);
            expect(toastWarning.mock.calls[0][0]).toBe(
                'These files may not fit in the remaining storage (100.0 MB free); overwritten files free up their space.'
            );
            const requests = takeStreamRequests();
            expect(requests.map(uploadedFileName)).toEqual(['a.pdf', 'b.pdf']);
            requests.forEach(succeed);
            expect(batch.result()?.uploaded.length).toBe(2);
        });

        it('does not warn when the files to send fit, leaving out the ones too large to send', () => {
            const limits: StorageUploadLimits = { ...UNCAPPED, max_file_size: 500 * MB, free_bytes: 100 * MB };
            startBatch([makeFile('a.pdf', 100 * MB), makeFile('too-big.pdf', 600 * MB)], limits);

            expect(toastWarning).not.toHaveBeenCalled();
            takeStreamRequests().forEach(succeed);
        });

        it.each([Number.NaN, Number.POSITIVE_INFINITY, null])('does not warn when free_bytes is %s', (freeBytes) => {
            startBatch([makeFile('a.pdf', 60 * MB)], { ...UNCAPPED, free_bytes: freeBytes });

            expect(toastWarning).not.toHaveBeenCalled();
            takeStreamRequests().forEach(succeed);
        });
    });

    describe('concurrency and retries', () => {
        it('keeps at most UPLOAD_CONCURRENCY uploads in flight', () => {
            const batch = startBatch(['a.txt', 'b.txt', 'c.txt', 'd.txt', 'e.txt']);

            const firstWave = takeStreamRequests();
            expect(firstWave.length).toBe(UPLOAD_CONCURRENCY);
            expect(firstWave.map(uploadedFileName)).toEqual(['a.txt', 'b.txt', 'c.txt']);

            succeed(firstWave[0]);
            const next = takeStreamRequests();
            expect(next.map(uploadedFileName)).toEqual(['d.txt']);

            [firstWave[1], firstWave[2], next[0]].forEach(succeed);
            const last = takeStreamRequests();
            expect(last.map(uploadedFileName)).toEqual(['e.txt']);
            succeed(last[0]);

            expect(batch.result()?.uploaded.length).toBe(5);
            expect(batch.result()?.failed).toEqual([]);
        });

        it('keeps the slot of a file waiting for Retry-After until that file settles', () => {
            vi.useFakeTimers();
            const batch = startBatch(['a.txt', 'b.txt', 'c.txt', 'd.txt']);
            const [first, second, third] = takeStreamRequests();

            first.flush(errorEnvelope(429, 'org_upload_limit_reached'), {
                status: 429,
                statusText: 'Too Many Requests',
                headers: { 'Retry-After': '2' },
            });
            expect(takeStreamRequests().length).toBe(0);

            vi.advanceTimersByTime(2000);
            const retried = takeStreamRequests();
            expect(retried.map(uploadedFileName)).toEqual(['a.txt']);

            succeed(retried[0]);
            const fourth = takeStreamRequests();
            expect(fourth.map(uploadedFileName)).toEqual(['d.txt']);

            [second, third, fourth[0]].forEach(succeed);
            expect(batch.result()?.uploaded.length).toBe(4);
        });

        it('lets siblings finish after one file fails and reports the partial success', () => {
            const batch = startBatch(['a.txt', 'bad.zip', 'c.txt']);
            const [first, bad, third] = takeStreamRequests();

            bad.flush(errorEnvelope(400, 'invalid', "Archive 'bad.zip' contains executable files: x.exe"), {
                status: 400,
                statusText: 'Bad Request',
            });
            expect(first.cancelled).toBe(false);
            expect(third.cancelled).toBe(false);
            expect(batch.result()).toBeUndefined();

            succeed(first);
            succeed(third);

            const result = batch.result();
            expect(uploadedNames(result)).toEqual(['a.txt', 'c.txt']);
            expect(result?.uploaded[0].result).toEqual({ type: 'file', path: 'a.txt', size: 7 });
            expect(failedNames(result)).toEqual(['bad.zip']);
        });

        it('stops sending new files after storage_quota_exceeded, letting in-flight ones finish', () => {
            const batch = startBatch(['a.txt', 'b.txt', 'c.txt', 'd.txt', 'e.txt']);
            const [first, second, third] = takeStreamRequests();

            first.flush(errorEnvelope(413, 'storage_quota_exceeded'), { status: 413, statusText: 'Payload Too Large' });
            expect(takeStreamRequests().length).toBe(0);

            succeed(second);
            succeed(third);
            expect(takeStreamRequests().length).toBe(0);

            const result = batch.result();
            expect(uploadedNames(result)).toEqual(['b.txt', 'c.txt']);
            const failures = new Map(result?.failed.map((failure) => [failure.file.name, failure.error]));
            expect(failures.get('a.txt')).toMatchObject({ status: 413 });
            expect(failures.get('d.txt')).toBeInstanceOf(UploadSkippedError);
            expect(failures.get('e.txt')).toBeInstanceOf(UploadSkippedError);
        });

        it('keeps sending the rest after upload_too_large (only the quota stops a batch)', () => {
            const batch = startBatch(['big.zip', 'b.txt', 'c.txt', 'd.txt']);
            const [big, second, third] = takeStreamRequests();

            big.flush(errorEnvelope(413, 'upload_too_large'), { status: 413, statusText: 'Payload Too Large' });
            const next = takeStreamRequests();
            expect(next.map(uploadedFileName)).toEqual(['d.txt']);

            [second, third, next[0]].forEach(succeed);
            expect(batch.result()?.uploaded.length).toBe(3);
            expect(failedNames(batch.result())).toEqual(['big.zip']);
        });
    });

    describe('uploadEach', () => {
        it('emits each outcome as soon as that file settles, too-large ones first', () => {
            const outcomes: StorageUploadOutcome[] = [];
            let completed = false;
            service
                .uploadEach('', [makeFile('big.pdf', 2 * MB), makeFile('a.txt'), makeFile('b.txt')])
                .subscribe({ next: (outcome) => outcomes.push(outcome), complete: () => (completed = true) });
            httpMock.expectOne(LIMITS_URL).flush({ ...UNCAPPED, max_file_size: MB });

            expect(outcomes.map((outcome) => [outcome.file.name, outcome.ok])).toEqual([['big.pdf', false]]);
            const [first, second] = takeStreamRequests();

            succeed(second);
            expect(outcomes.map((outcome) => outcome.file.name)).toEqual(['big.pdf', 'b.txt']);
            expect(completed).toBe(false);

            succeed(first);
            expect(outcomes.map((outcome) => outcome.file.name)).toEqual(['big.pdf', 'b.txt', 'a.txt']);
            expect(completed).toBe(true);
        });
    });

    describe('unsubscribing', () => {
        it('cancels the limits request', () => {
            const batch = startBatchWithoutLimits(['a.txt']);
            const limitsRequest = httpMock.expectOne(LIMITS_URL);

            batch.subscription.unsubscribe();

            expect(limitsRequest.cancelled).toBe(true);
            expect(takeStreamRequests().length).toBe(0);
        });

        it('cancels in-flight uploads and starts no queued ones', () => {
            const batch = startBatch(['a.txt', 'b.txt', 'c.txt', 'd.txt']);
            const inFlight = takeStreamRequests();
            expect(inFlight.length).toBe(UPLOAD_CONCURRENCY);

            batch.subscription.unsubscribe();

            expect(inFlight.every((request) => request.cancelled)).toBe(true);
            expect(takeStreamRequests().length).toBe(0);
            expect(batch.result()).toBeUndefined();
        });

        it('clears a pending retry timer so the file is never re-sent', () => {
            vi.useFakeTimers();
            const batch = startBatch(['a.txt']);
            takeStreamRequests()[0].flush(errorEnvelope(503, 'upload_slots_busy'), {
                status: 503,
                statusText: 'Service Unavailable',
                headers: { 'Retry-After': '5' },
            });
            expect(vi.getTimerCount()).toBe(1);

            batch.subscription.unsubscribe();

            expect(vi.getTimerCount()).toBe(0);
            vi.advanceTimersByTime(60_000);
            expect(takeStreamRequests().length).toBe(0);
        });
    });
});
