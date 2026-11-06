import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../services/config';
import { TransferJob } from '../models/transfer-job.model';
import { TRANSFER_JOB_MAX_WAIT_MS, TRANSFER_JOB_POLL_INTERVAL_MS, TransferJobsService } from './transfer-jobs.service';

const JOB_ID = '0b9c6c0e-5d8e-4a8e-9f0a-1c2d3e4f5a6b';
const JOB_URL = `/api/transfer-jobs/${JOB_ID}/`;

function exportJob(overrides: Partial<TransferJob> = {}): TransferJob {
    return {
        id: JOB_ID,
        kind: 'export',
        main_entity: 'Flow',
        status: 'running',
        file_name: null,
        result: null,
        error: null,
        created_at: '2026-11-06T10:00:00Z',
        finished_at: null,
        expires_at: null,
        ...overrides,
    } as TransferJob;
}

interface Outcome {
    values: TransferJob[];
    error: Error | null;
    completed: boolean;
}

describe('TransferJobsService', () => {
    let service: TransferJobsService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            ],
        });
        service = TestBed.inject(TransferJobsService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        httpMock.verify();
        vi.useRealTimers();
        vi.restoreAllMocks();
    });

    describe('waitForJob', () => {
        function waitForJob(): Outcome {
            const outcome: Outcome = { values: [], error: null, completed: false };
            service.waitForJob(JOB_ID).subscribe({
                next: (job) => outcome.values.push(job),
                error: (error: Error) => (outcome.error = error),
                complete: () => (outcome.completed = true),
            });
            // The first poll goes out right away, on the next timer tick.
            vi.advanceTimersByTime(0);
            return outcome;
        }

        beforeEach(() => vi.useFakeTimers());

        it('polls until the job has completed and emits it once', () => {
            const outcome = waitForJob();

            httpMock.expectOne(JOB_URL).flush(exportJob({ status: 'queued' }));
            vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS);
            httpMock.expectOne(JOB_URL).flush(exportJob({ status: 'running' }));
            expect(outcome.values).toEqual([]);

            vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS);
            const completed = exportJob({ status: 'completed', file_name: 'Orders.zip', result: { excluded: [] } });
            httpMock.expectOne(JOB_URL).flush(completed);

            expect(outcome).toEqual({ values: [completed], error: null, completed: true });
            vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS * 3);
            httpMock.expectNone(JOB_URL);
        });

        it('stops on a failed job with the message the server gave', () => {
            const outcome = waitForJob();

            httpMock
                .expectOne(JOB_URL)
                .flush(
                    exportJob({ status: 'failed', error: { code: 'export_failed', message: 'Collection 4 is gone.' } })
                );

            expect(outcome.values).toEqual([]);
            expect(outcome.error?.message).toBe('Collection 4 is gone.');
            vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS * 3);
            httpMock.expectNone(JOB_URL);
        });

        it('gives up when the job is still running after the longest wait', () => {
            const outcome = waitForJob();

            for (let waited = 0; waited < TRANSFER_JOB_MAX_WAIT_MS; waited += TRANSFER_JOB_POLL_INTERVAL_MS) {
                httpMock.match(JOB_URL).forEach((request) => request.flush(exportJob({ status: 'running' })));
                expect(outcome.error).toBeNull();
                vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS);
            }
            httpMock.match(JOB_URL).forEach((request) => expect(request.cancelled).toBe(true));

            expect(outcome.values).toEqual([]);
            expect(outcome.error?.message).toBe('The job is taking too long. Try again later.');
        });
    });

    describe('downloadExport', () => {
        it('asks for a download ticket and navigates the browser to it, without fetching the archive', () => {
            const clickedLinks: HTMLAnchorElement[] = [];
            vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
                clickedLinks.push(this);
            });
            let done = false;

            service
                .downloadExport(exportJob({ status: 'completed', file_name: 'Orders.zip' }))
                .subscribe(() => (done = true));
            expect(clickedLinks).toEqual([]);

            const ticketRequest = httpMock.expectOne(`/api/transfer-jobs/${JOB_ID}/download-ticket/`);
            expect(ticketRequest.request.method).toBe('POST');
            ticketRequest.flush({ download_url: `/api/transfer-jobs/${JOB_ID}/download/?ticket=t-1` });

            expect(done).toBe(true);
            expect(clickedLinks.map((link) => link.href)).toEqual([
                new URL(`/api/transfer-jobs/${JOB_ID}/download/?ticket=t-1`, document.baseURI).href,
            ]);
            expect(clickedLinks[0].download).toBe('Orders.zip');
        });
    });

    describe('startImport', () => {
        it('uploads the archive as the raw body with the flow import settings in the query', () => {
            const archive = new File(['PK'], 'flows.zip');

            service
                .startImport('flows', archive, { preserveUuids: true, replaceExisting: true, importLabels: false })
                .subscribe();

            const request = httpMock.expectOne(
                (candidate) => candidate.url === '/api/graphs/import-jobs/' && candidate.method === 'POST'
            );
            expect(request.request.body).toBe(archive);
            expect(request.request.headers.get('Content-Type')).toBe('application/zip');
            expect(request.request.params.toString()).toBe(
                'preserve_uuids=true&replace_existing=true&import_labels=false'
            );
            request.flush({ job_id: JOB_ID }, { status: 202, statusText: 'Accepted' });
        });

        it('uploads a collection archive with no query', () => {
            const archive = new File(['PK'], 'collections.zip');

            service.startImport('collections', archive).subscribe();

            const request = httpMock.expectOne('/api/source-collections/import-jobs/');
            expect(request.request.body).toBe(archive);
            expect(request.request.params.keys()).toEqual([]);
            request.flush({ job_id: JOB_ID }, { status: 202, statusText: 'Accepted' });
        });
    });
});
