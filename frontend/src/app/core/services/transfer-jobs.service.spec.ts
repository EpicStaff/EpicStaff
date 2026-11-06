import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Observable } from 'rxjs';

import { ActiveOrgService } from '../../services/auth/active-org.service';
import { PermissionsService } from '../../services/auth/permissions.service';
import { SessionEndService } from '../../services/auth/session-end.service';
import { ConfigService } from '../../services/config';
import { activeOrgInterceptor } from '../interceptors/active-org.interceptor';
import { ImportResult } from '../models/import-result.model';
import { TransferJob, TransferJobKind } from '../models/transfer-job.model';
import {
    DOWNLOAD_FRAME_LIFETIME_MS,
    StartedTransferJob,
    TRANSFER_JOB_MAX_WAIT_MS,
    TRANSFER_JOB_POLL_INTERVAL_MS,
    TRANSFER_JOB_POLL_RETRIES,
    TransferJobsService,
} from './transfer-jobs.service';

const JOB_ID = '0b9c6c0e-5d8e-4a8e-9f0a-1c2d3e4f5a6b';
const JOB_URL = `/api/transfer-jobs/${JOB_ID}/`;
const TICKET_URL = `/api/transfer-jobs/${JOB_ID}/download-ticket/`;
const STARTED_EXPORT: StartedTransferJob = { id: JOB_ID, kind: 'export', orgId: 7 };
const SUMMARY: ImportResult = {
    SourceCollection: {
        total: 1,
        created: { count: 1, items: [{ id: 3, name: 'Handbook' }] },
        reused: { count: 0, items: [] },
    },
};

function transferJob(overrides: Partial<TransferJob> = {}): TransferJob {
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

interface Outcome<T> {
    values: T[];
    error: Error | null;
    completed: boolean;
}

function observe<T>(source: Observable<T>): Outcome<T> {
    const outcome: Outcome<T> = { values: [], error: null, completed: false };
    source.subscribe({
        next: (value) => outcome.values.push(value),
        error: (error: Error) => (outcome.error = error),
        complete: () => (outcome.completed = true),
    });
    return outcome;
}

describe('TransferJobsService', () => {
    let service: TransferJobsService;
    let httpMock: HttpTestingController;
    let activeOrg: ActiveOrgService;

    function setUp(apiUrl = '/api/'): void {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(withInterceptors([activeOrgInterceptor])),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl } },
                // A member, not a superadmin: the org pinning must hold for every user.
                { provide: PermissionsService, useValue: { isSuperadmin: false } },
            ],
        });
        service = TestBed.inject(TransferJobsService);
        httpMock = TestBed.inject(HttpTestingController);
        activeOrg = TestBed.inject(ActiveOrgService);
        activeOrg.set(7);
    }

    afterEach(() => {
        httpMock.verify();
        activeOrg.clear();
        vi.useRealTimers();
        vi.restoreAllMocks();
    });

    describe('waitForJob', () => {
        beforeEach(() => {
            setUp();
            vi.useFakeTimers();
        });

        function waitForJob(started: StartedTransferJob = STARTED_EXPORT): Outcome<TransferJob> {
            const outcome = observe(service.waitForJob(started));
            // The first poll goes out right away, on the next timer tick.
            vi.advanceTimersByTime(0);
            return outcome;
        }

        it('polls until the job has completed and emits it once', () => {
            const outcome = waitForJob();

            httpMock.expectOne(JOB_URL).flush(transferJob({ status: 'queued' }));
            vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS);
            httpMock.expectOne(JOB_URL).flush(transferJob({ status: 'running' }));
            expect(outcome.values).toEqual([]);

            vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS);
            const completed = transferJob({ status: 'completed', file_name: 'Orders.zip', result: { excluded: [] } });
            httpMock.expectOne(JOB_URL).flush(completed);

            expect(outcome).toEqual({ values: [completed], error: null, completed: true });
            vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS * 3);
            httpMock.expectNone(JOB_URL);
        });

        it('stops on a failed job with the message the server gave', () => {
            const outcome = waitForJob();

            httpMock.expectOne(JOB_URL).flush(
                transferJob({
                    status: 'failed',
                    error: { code: 'export_failed', message: 'Collection 4 is gone.' },
                })
            );

            expect(outcome.values).toEqual([]);
            expect(outcome.error?.message).toBe('Collection 4 is gone.');
            vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS * 3);
            httpMock.expectNone(JOB_URL);
        });

        it.each<[TransferJobKind, string]>([
            [
                'export',
                'The export is taking longer than usual and is still running on the server. Export again later to ' +
                    'download it.',
            ],
            [
                'import',
                'The import is taking longer than usual and is still running on the server. Check the list again in ' +
                    'a few minutes before you import the file again, so it is not imported twice.',
            ],
        ])('gives up on an %s still running after the longest wait, saying it still runs', (kind, message) => {
            const outcome = waitForJob({ ...STARTED_EXPORT, kind });

            for (let waited = 0; waited < TRANSFER_JOB_MAX_WAIT_MS; waited += TRANSFER_JOB_POLL_INTERVAL_MS) {
                httpMock.match(JOB_URL).forEach((request) => request.flush(transferJob({ status: 'running' })));
                expect(outcome.error).toBeNull();
                vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS);
            }
            httpMock.match(JOB_URL).forEach((request) => expect(request.cancelled).toBe(true));

            expect(outcome.values).toEqual([]);
            expect(outcome.error?.message).toBe(message);
        });

        it('keeps polling the organization the job started in after the user switches to another', () => {
            const outcome = waitForJob({ ...STARTED_EXPORT, orgId: 7 });
            httpMock.expectOne(JOB_URL).flush(transferJob({ status: 'running' }));

            activeOrg.set(9);
            vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS);

            const poll = httpMock.expectOne(JOB_URL);
            expect(poll.request.headers.get('X-Organization-Id')).toBe('7');
            poll.flush(transferJob({ status: 'completed' }));

            expect(outcome.values).toHaveLength(1);
        });

        describe('when a poll fails', () => {
            const NETWORK_DROP = { status: 0, statusText: 'Unknown Error' };
            const BAD_GATEWAY = { status: 502, statusText: 'Bad Gateway' };

            function failPoll(response: { status: number; statusText: string }): void {
                const poll = httpMock.expectOne(JOB_URL);
                if (response.status === 0) {
                    poll.error(new ProgressEvent('error'), response);
                } else {
                    poll.flush(null, response);
                }
            }

            it('retries after a network drop or a server error and still finishes the wait', () => {
                const outcome = waitForJob();

                failPoll(BAD_GATEWAY);
                vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS);
                failPoll(NETWORK_DROP);
                vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS);
                httpMock.expectOne(JOB_URL).flush(transferJob({ status: 'completed' }));

                expect(outcome.error).toBeNull();
                expect(outcome.values).toHaveLength(1);
            });

            it('gives up once the server keeps failing', () => {
                const outcome = waitForJob();

                for (let attempt = 0; attempt < TRANSFER_JOB_POLL_RETRIES; attempt++) {
                    failPoll(BAD_GATEWAY);
                    expect(outcome.error).toBeNull();
                    vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS);
                }
                failPoll(BAD_GATEWAY);

                expect(outcome.error).toMatchObject({ status: 502 });
                vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS * 3);
                httpMock.expectNone(JOB_URL);
            });

            it.each([
                [404, 'Not Found'],
                [403, 'Forbidden'],
            ])('ends the wait at once on a %s, which a retry would not change', (status, statusText) => {
                const outcome = waitForJob();

                failPoll({ status, statusText });

                expect(outcome.error).toMatchObject({ status });
                vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS * 3);
                httpMock.expectNone(JOB_URL);
            });
        });

        it('stops waiting, with no value and no error, when the user signs out', () => {
            const outcome = waitForJob();
            httpMock.expectOne(JOB_URL).flush(transferJob({ status: 'running' }));
            vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS);
            const pendingPoll = httpMock.expectOne(JOB_URL);

            TestBed.inject(SessionEndService).notifyEnded();

            expect(pendingPoll.cancelled).toBe(true);
            expect(outcome).toEqual({ values: [], error: null, completed: true });
            vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS * 3);
            httpMock.expectNone(JOB_URL);
        });
    });

    describe('starting a job', () => {
        beforeEach(() => setUp());

        it('remembers the organization it started in and sends the start there', () => {
            const outcome = observe(service.startCollectionExport([4]));
            activeOrg.set(9);

            const start = httpMock.expectOne('/api/source-collections/export-jobs/');
            expect(start.request.headers.get('X-Organization-Id')).toBe('7');
            start.flush({ job_id: JOB_ID }, { status: 202, statusText: 'Accepted' });

            expect(outcome.values).toEqual([{ id: JOB_ID, kind: 'export', orgId: 7 }]);
        });

        it('uploads the archive as the raw body with the flow import settings in the query', () => {
            const archive = new File(['PK'], 'flows.zip');

            const outcome = observe(
                service.startImport('flows', archive, {
                    preserveUuids: true,
                    replaceExisting: true,
                    importLabels: false,
                })
            );

            const request = httpMock.expectOne(
                (candidate) => candidate.url === '/api/graphs/import-jobs/' && candidate.method === 'POST'
            );
            expect(request.request.body).toBe(archive);
            expect(request.request.headers.get('Content-Type')).toBe('application/zip');
            expect(request.request.params.toString()).toBe(
                'preserve_uuids=true&replace_existing=true&import_labels=false'
            );
            request.flush({ job_id: JOB_ID }, { status: 202, statusText: 'Accepted' });
            expect(outcome.values).toEqual([{ id: JOB_ID, kind: 'import', orgId: 7 }]);
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

    describe('importAndWait', () => {
        beforeEach(() => setUp());

        async function finishImport(job: TransferJob): Promise<void> {
            httpMock
                .expectOne('/api/source-collections/import-jobs/')
                .flush({ job_id: JOB_ID }, { status: 202, statusText: 'Accepted' });
            (await vi.waitFor(() => httpMock.expectOne(JOB_URL))).flush(job);
        }

        it("emits the finished import's summary", async () => {
            const outcome = observe(service.importAndWait('collections', new File(['PK'], 'collections.zip')));

            await finishImport(transferJob({ kind: 'import', status: 'completed', result: SUMMARY }));

            expect(outcome).toEqual({ values: [SUMMARY], error: null, completed: true });
        });

        it('emits null for an import that completed without a summary', async () => {
            const outcome = observe(service.importAndWait('collections', new File(['PK'], 'collections.zip')));

            await finishImport(transferJob({ kind: 'import', status: 'completed', result: null }));

            expect(outcome).toEqual({ values: [null], error: null, completed: true });
        });
    });

    describe('downloadExport', () => {
        let clickedLinks: HTMLAnchorElement[];

        beforeEach(() => {
            clickedLinks = [];
            vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
                clickedLinks.push(this);
            });
        });

        afterEach(() => document.querySelectorAll('iframe').forEach((frame) => frame.remove()));

        function requestTicket(): TestRequest {
            const ticketRequest = httpMock.expectOne(TICKET_URL);
            expect(ticketRequest.request.method).toBe('POST');
            return ticketRequest;
        }

        it('asks for a download ticket in the organization of the job and has the link download the archive', () => {
            setUp();
            // The job started in org 7; the user has switched to org 9 since.
            activeOrg.set(9);
            const outcome = observe(service.downloadExport(STARTED_EXPORT, 'Orders.zip'));
            expect(clickedLinks).toEqual([]);

            const ticketRequest = requestTicket();
            expect(ticketRequest.request.headers.get('X-Organization-Id')).toBe('7');
            ticketRequest.flush({ download_url: `/api/transfer-jobs/${JOB_ID}/download/?ticket=t-1` });

            expect(outcome.completed).toBe(true);
            expect(clickedLinks.map((link) => [link.href, link.download])).toEqual([
                [new URL(`/api/transfer-jobs/${JOB_ID}/download/?ticket=t-1`, document.baseURI).href, 'Orders.zip'],
            ]);
            expect(document.querySelector('iframe')).toBeNull();
        });

        it('downloads from an API on another origin in a hidden frame, so an error answer cannot replace the app', () => {
            vi.useFakeTimers();
            setUp('https://api.example.com/api/');
            service.downloadExport(STARTED_EXPORT, 'Orders.zip').subscribe();

            httpMock
                .expectOne(`https://api.example.com/api/transfer-jobs/${JOB_ID}/download-ticket/`)
                .flush({ download_url: `/api/transfer-jobs/${JOB_ID}/download/?ticket=t-1` });

            const frame = document.querySelector('iframe');
            expect(clickedLinks).toEqual([]);
            expect(frame?.hidden).toBe(true);
            expect(frame?.src).toBe(`https://api.example.com/api/transfer-jobs/${JOB_ID}/download/?ticket=t-1`);

            vi.advanceTimersByTime(DOWNLOAD_FRAME_LIFETIME_MS);
            expect(document.querySelector('iframe')).toBeNull();
        });
    });
});
