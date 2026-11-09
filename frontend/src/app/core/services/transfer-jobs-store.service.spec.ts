import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Subscription } from 'rxjs';
import { switchMap } from 'rxjs/operators';

import { ActiveOrgService } from '../../services/auth/active-org.service';
import { ProfileService } from '../../services/auth/profile.service';
import { SessionEndService } from '../../services/auth/session-end.service';
import { ConfigService } from '../../services/config';
import { ToastMessage, ToastService } from '../../services/notifications';
import { isUnfinishedTransferJob, TransferJob } from '../models/transfer-job.model';
import { TransferJobsService } from './transfer-jobs.service';
import { TRANSFER_JOBS_LIST_POLL_INTERVAL_MS, TransferJobsStoreService } from './transfer-jobs-store.service';

const LIST_URL = '/api/transfer-jobs/';

function job(overrides: Partial<TransferJob> = {}): TransferJob {
    return {
        id: 'job-1',
        kind: 'export',
        main_entity: 'Flow',
        status: 'running',
        display_name: 'Orders',
        file_name: null,
        result: null,
        error: null,
        created_at: '2026-11-06T10:00:00Z',
        finished_at: null,
        expires_at: null,
        ...overrides,
    } as TransferJob;
}

function page(...jobs: TransferJob[]): { count: number; results: TransferJob[] } {
    return { count: jobs.length, results: jobs };
}

describe('TransferJobsStoreService', () => {
    let store: TransferJobsStoreService;
    let httpMock: HttpTestingController;
    let user: WritableSignal<{ id: number } | null>;
    let orgId: WritableSignal<number | null>;
    let toasts: ToastMessage[];

    beforeEach(() => {
        vi.useFakeTimers();
        user = signal({ id: 1 });
        orgId = signal(7);
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                { provide: ProfileService, useValue: { currentUserSignal: user } },
                { provide: ActiveOrgService, useValue: { activeOrgId: orgId } },
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
        TestBed.inject(ToastService).toasts$.subscribe((current) => (toasts = current));
        store = TestBed.inject(TransferJobsStoreService);
        TestBed.tick();
    });

    afterEach(() => {
        httpMock.verify();
        vi.useRealTimers();
        vi.restoreAllMocks();
    });

    function expectFullList(): TestRequest {
        return httpMock.expectOne((request) => request.url === LIST_URL && !request.params.has('status'));
    }

    function expectUnfinishedCheck(): TestRequest {
        return httpMock.expectOne(
            (request) => request.url === LIST_URL && request.params.getAll('status')?.join() === 'queued,running'
        );
    }

    /** Answers a load of the list: the first page with these jobs, and the unfinished ones among them. */
    function answerLoad(...jobs: TransferJob[]): void {
        expectFullList().flush(page(...jobs));
        expectUnfinishedCheck().flush(page(...jobs.filter(isUnfinishedTransferJob)));
    }

    function expectNoListRequest(): void {
        httpMock.expectNone((request) => request.url === LIST_URL);
    }

    function nextCheck(): void {
        vi.advanceTimersByTime(TRANSFER_JOBS_LIST_POLL_INTERVAL_MS);
    }

    const READY_MESSAGE = 'The export of "Orders" is ready. Its archive is also in Exports and imports.';
    const COMPLETED_EXPORT = job({ status: 'completed', file_name: 'Orders.zip', result: { excluded: [] } });

    it('follows a job left unfinished before the page was loaded and offers its archive once ready', () => {
        answerLoad(job({ status: 'running' }));
        expect(store.unfinishedCount()).toBe(1);

        nextCheck();
        expectUnfinishedCheck().flush(page());
        answerLoad(COMPLETED_EXPORT);

        expect(store.unfinishedCount()).toBe(0);
        expect(store.jobs().map((listed) => listed.status)).toEqual(['completed']);
        const ready = toasts.find((toast) => toast.action !== null);
        expect(ready?.message).toBe(READY_MESSAGE);
        // Offered, not downloaded on its own.
        httpMock.expectNone('/api/transfer-jobs/job-1/download-ticket/');

        ready?.action?.run();
        httpMock.expectOne('/api/transfer-jobs/job-1/download-ticket/');
    });

    it('announces a resumed job that failed with the reason the server gave', () => {
        answerLoad(job({ status: 'queued' }));

        nextCheck();
        expectUnfinishedCheck().flush(page());
        answerLoad(job({ status: 'failed', error: { code: 'export_failed', message: 'Flow 4 is gone.' } }));

        expect(toasts.map((toast) => [toast.type, toast.message])).toEqual([
            ['error', 'The export of "Orders" failed. Flow 4 is gone.'],
        ]);
    });

    it('announces nothing about jobs that had already ended when the page was loaded', () => {
        answerLoad(COMPLETED_EXPORT, job({ id: 'job-2', status: 'failed' }));

        store.reload();
        answerLoad(COMPLETED_EXPORT, job({ id: 'job-2', status: 'failed' }));

        expect(toasts).toEqual([]);
    });

    it('updates a job that moved from queued to running without loading the whole list', () => {
        answerLoad(job({ status: 'queued' }));

        nextCheck();
        expectUnfinishedCheck().flush(page(job({ status: 'running' })));

        expect(store.jobs().map((listed) => listed.status)).toEqual(['running']);
        httpMock.expectNone((request) => request.url === LIST_URL && !request.params.has('status'));
        nextCheck();
        expectUnfinishedCheck();
    });

    it('checks nothing while no job is unfinished', () => {
        answerLoad(job({ status: 'completed' }), job({ id: 'job-2', status: 'failed' }));

        nextCheck();
        nextCheck();

        expectNoListRequest();
        expect(store.unfinishedCount()).toBe(0);
    });

    it('counts and follows an unfinished job older than the jobs the first page holds', () => {
        expectFullList().flush({ count: 51, results: [COMPLETED_EXPORT] });
        expectUnfinishedCheck().flush(page(job({ id: 'old-job', status: 'running' })));

        expect(store.totalCount()).toBe(51);
        expect(store.unfinishedCount()).toBe(1);
        nextCheck();
        expectUnfinishedCheck();
    });

    it('stops checking once the last unfinished job has ended', () => {
        answerLoad(job({ status: 'running' }));
        nextCheck();
        expectUnfinishedCheck().flush(page());
        answerLoad(job({ status: 'completed' }));

        nextCheck();
        nextCheck();

        expectNoListRequest();
    });

    it('loads the jobs of the organization the user switched to', () => {
        answerLoad(job({ id: 'job-in-7', status: 'running' }));

        orgId.set(9);
        TestBed.tick();

        expect(store.jobs()).toEqual([]);
        answerLoad(job({ id: 'job-in-9', status: 'completed' }));
        expect(store.jobs().map((listed) => listed.id)).toEqual(['job-in-9']);
        // The job of the organization left behind is no longer checked.
        nextCheck();
        expectNoListRequest();
    });

    it('stops and forgets the jobs on sign-out', () => {
        answerLoad(job({ status: 'running' }));

        TestBed.inject(SessionEndService).notifyEnded();

        expect(store.jobs()).toEqual([]);
        expect(store.unfinishedCount()).toBe(0);
        nextCheck();
        nextCheck();
        expectNoListRequest();
    });

    describe('a job this tab starts', () => {
        const JOB_URL = '/api/transfer-jobs/job-1/';
        let transferJobs: TransferJobsService;

        beforeEach(() => {
            transferJobs = TestBed.inject(TransferJobsService);
            answerLoad();
        });

        /** Starts an export and waits for it, as the page that starts one does; it is listed as queued. */
        function startAndWait(): Subscription {
            const subscription = transferJobs
                .startExport('mcpTools', { ids: [4] })
                .pipe(switchMap((started) => transferJobs.waitForJob(started)))
                .subscribe({ error: () => undefined });
            httpMock.expectOne('/api/mcp-tools/export-jobs/').flush({ job_id: 'job-1' });
            answerLoad(job({ status: 'queued' }));
            vi.advanceTimersByTime(0);
            httpMock.expectOne(JOB_URL).flush(job({ status: 'queued' }));
            return subscription;
        }

        /** The check finds the job ended and the list is loaded again. */
        function checkFindsEnded(ended: TransferJob): void {
            nextCheck();
            expectUnfinishedCheck().flush(page());
            answerLoad(ended);
        }

        function pendingWaitPolls(): TestRequest[] {
            return httpMock.match(JOB_URL).filter((request) => !request.cancelled);
        }

        it('is listed, and its end is left to the wait that tells it', () => {
            startAndWait();
            expect(store.unfinishedCount()).toBe(1);

            checkFindsEnded(COMPLETED_EXPORT);
            expect(toasts).toEqual([]);

            pendingWaitPolls().forEach((poll) => poll.flush(COMPLETED_EXPORT));
            store.reload();
            answerLoad(COMPLETED_EXPORT);

            expect(toasts).toEqual([]);
        });

        it('is announced when the page that waited for it was left before it ended', () => {
            const wait = startAndWait();

            wait.unsubscribe();
            checkFindsEnded(COMPLETED_EXPORT);

            expect(toasts.map((toast) => toast.message)).toEqual([READY_MESSAGE]);
        });

        it('is announced when the page that waited was left after the check had found it ended', () => {
            const wait = startAndWait();
            checkFindsEnded(job({ status: 'failed', error: { code: 'export_failed', message: 'Disk full.' } }));
            expect(toasts).toEqual([]);

            wait.unsubscribe();

            expect(toasts.map((toast) => toast.message)).toEqual(['The export of "Orders" failed. Disk full.']);
            expect(httpMock.match(JOB_URL).every((poll) => poll.cancelled)).toBe(true);
        });
    });

    it('lists a job started in another tab when a check finds it, and leaves announcing its end to that tab', () => {
        answerLoad(job({ status: 'running' }));

        nextCheck();
        expectUnfinishedCheck().flush(page(job({ status: 'running' }), job({ id: 'job-2', status: 'queued' })));
        answerLoad(job({ id: 'job-2', display_name: 'Invoices', status: 'queued' }), job({ status: 'running' }));
        expect(store.unfinishedCount()).toBe(2);

        nextCheck();
        expectUnfinishedCheck().flush(page());
        answerLoad(
            job({ id: 'job-2', display_name: 'Invoices', status: 'completed', file_name: 'Invoices.zip' }),
            COMPLETED_EXPORT
        );

        expect(toasts.map((toast) => toast.message)).toEqual([READY_MESSAGE]);
    });

    describe('paging', () => {
        function finishedJobs(count: number): TransferJob[] {
            return Array.from({ length: count }, (_, index) =>
                job({ id: `job-${index + 1}`, status: 'completed', file_name: 'a.zip', result: { excluded: [] } })
            );
        }

        function expectPage(offset: number): TestRequest {
            return httpMock.expectOne(
                (request) =>
                    request.url === LIST_URL &&
                    request.params.get('offset') === String(offset) &&
                    request.params.get('limit') === '10'
            );
        }

        function ids(): string[] {
            return store.jobs().map((listed) => listed.id);
        }

        it('loads again every job the user has paged to, so a refresh keeps them listed', () => {
            const server = finishedJobs(25);
            expectFullList().flush({ count: 25, results: server.slice(0, 10) });
            expectUnfinishedCheck().flush(page());
            store.loadMore();
            expectPage(10).flush({ count: 25, results: server.slice(10, 20) });

            store.reload();
            const refresh = expectFullList();
            expect([refresh.request.params.get('limit'), refresh.request.params.get('offset')]).toEqual(['20', null]);
            refresh.flush({ count: 25, results: server.slice(0, 20) });
            expectUnfinishedCheck().flush(page());

            expect(ids()).toEqual(server.slice(0, 20).map((listed) => listed.id));
            expect(store.remainingCount()).toBe(5);
        });

        it('keeps a page that came while the list was loading again', () => {
            const server = finishedJobs(25);
            expectFullList().flush({ count: 25, results: server.slice(0, 10) });
            expectUnfinishedCheck().flush(page());

            store.reload();
            const refresh = expectFullList();
            const check = expectUnfinishedCheck();
            store.loadMore();
            expectPage(10).flush({ count: 25, results: server.slice(10, 20) });
            refresh.flush({ count: 25, results: server.slice(0, 10) });
            check.flush(page());

            expect(ids()).toEqual(server.slice(0, 20).map((listed) => listed.id));
        });

        it('drops a listed job the server no longer has once every job fits the refreshed list', () => {
            const server = finishedJobs(12);
            expectFullList().flush({ count: 12, results: server.slice(0, 10) });
            expectUnfinishedCheck().flush(page());
            store.loadMore();
            expectPage(10).flush({ count: 12, results: server.slice(10) });

            // Another tab cleared the oldest job.
            store.reload();
            expectFullList().flush(page(...server.slice(0, 11)));
            expectUnfinishedCheck().flush(page());

            expect(ids()).toEqual(server.slice(0, 11).map((listed) => listed.id));
        });

        it('asks for nothing more once every job is listed', () => {
            answerLoad(...finishedJobs(10));

            store.loadMore();

            expectNoListRequest();
            expect(store.remainingCount()).toBe(0);
        });

        it('drops a page still loading when the organization changes', () => {
            expectFullList().flush({ count: 25, results: finishedJobs(10) });
            expectUnfinishedCheck().flush(page());
            store.loadMore();
            const stale = expectPage(10);

            orgId.set(9);
            TestBed.tick();

            expect(stale.cancelled).toBe(true);
            expect(store.isLoadingMore()).toBe(false);
            answerLoad();
        });
    });

    it('reports that nothing could be loaded', () => {
        expectFullList().flush({ message: 'Down' }, { status: 500, statusText: 'Server Error' });
        expectUnfinishedCheck();

        expect(store.loadFailed()).toBe(true);
        expect(store.isLoading()).toBe(false);
    });

    describe('clearing a job', () => {
        it('removes a finished job once the server has deleted it', () => {
            const finished = job({ status: 'completed' });
            answerLoad(finished, job({ id: 'job-2', status: 'failed' }));

            store.clearJob(finished);
            expect(store.clearingIds().has('job-1')).toBe(true);
            const request = httpMock.expectOne('/api/transfer-jobs/job-1/');
            expect(request.request.method).toBe('DELETE');
            request.flush(null, { status: 204, statusText: 'No Content' });

            expect(store.jobs().map((listed) => listed.id)).toEqual(['job-2']);
            expect(store.clearingIds().size).toBe(0);
        });

        it('sends nothing for a running job', () => {
            const running = job({ status: 'running' });
            answerLoad(running);

            store.clearJob(running);

            httpMock.expectNone('/api/transfer-jobs/job-1/');
            expect(store.jobs()).toHaveLength(1);
        });

        it('keeps a job that started running meanwhile, says why and loads the list again', () => {
            const queued = job({ status: 'queued' });
            answerLoad(queued);

            store.clearJob(queued);
            httpMock
                .expectOne('/api/transfer-jobs/job-1/')
                .flush(
                    { code: 'job_running', message: 'The job is running.' },
                    { status: 409, statusText: 'Conflict' }
                );

            expect(store.jobs()).toHaveLength(1);
            expect(toasts.map((toast) => toast.message)).toEqual(['The job is running.']);
            expectFullList();
            expectUnfinishedCheck();
        });

        it('removes a job the server no longer has', () => {
            const finished = job({ status: 'completed' });
            answerLoad(finished);

            store.clearJob(finished);
            httpMock.expectOne('/api/transfer-jobs/job-1/').flush(null, { status: 404, statusText: 'Not Found' });

            expect(store.jobs()).toEqual([]);
        });
    });

    describe('clearing all jobs', () => {
        const CLEAR_URL = '/api/transfer-jobs/clear/';
        const RUNNING = job({ id: 'job-2', status: 'running' });

        function expectClear(): TestRequest {
            return httpMock.expectOne((request) => request.url === CLEAR_URL && request.method === 'POST');
        }

        it('asks the server to clear, then shows the jobs it kept and how many are still unfinished', () => {
            answerLoad(COMPLETED_EXPORT, RUNNING, job({ id: 'job-3', status: 'queued' }));

            store.clearAll();
            expect(store.isClearingAll()).toBe(true);
            expectClear().flush({ deleted: 2 });
            answerLoad(RUNNING);

            expect(store.jobs().map((listed) => listed.id)).toEqual(['job-2']);
            expect(store.unfinishedCount()).toBe(1);
            expect(store.isClearingAll()).toBe(false);
            expect(toasts.map((toast) => [toast.type, toast.message])).toEqual([['success', 'Cleared 2 jobs.']]);
        });

        it('says nothing was cleared, not "Cleared 0 jobs", when every job left had started running', () => {
            answerLoad(job({ id: 'job-3', status: 'queued' }), RUNNING);

            store.clearAll();
            expectClear().flush({ deleted: 0 });
            answerLoad(job({ id: 'job-3', status: 'running' }), RUNNING);

            expect(toasts.map((toast) => [toast.type, toast.message])).toEqual([
                ['info', 'Nothing to clear. Running jobs are kept.'],
            ]);
        });

        it('sends one request while one is on its way', () => {
            answerLoad(COMPLETED_EXPORT);

            store.clearAll();
            store.clearAll();

            expectClear().flush({ deleted: 1 });
            answerLoad();
        });

        it('says why it failed and loads the list again, as some jobs may be gone', () => {
            answerLoad(COMPLETED_EXPORT);

            store.clearAll();
            expectClear().flush({ message: 'The server is busy.' }, { status: 500, statusText: 'Server Error' });

            expect(toasts.map((toast) => [toast.type, toast.message])).toEqual([['error', 'The server is busy.']]);
            expect(store.isClearingAll()).toBe(false);
            answerLoad();
            expect(store.jobs()).toEqual([]);
        });

        it.each([
            { case: 'no jobs at all', listed: [], total: 0, expected: false },
            { case: 'only running jobs, all listed', listed: [RUNNING], total: 1, expected: false },
            { case: 'a queued job', listed: [RUNNING, job({ status: 'queued' })], total: 2, expected: true },
            { case: 'a failed job', listed: [job({ status: 'failed' })], total: 1, expected: true },
            { case: 'running jobs listed and more not listed yet', listed: [RUNNING], total: 11, expected: true },
        ])('has something to clear with $case: $expected', ({ listed, total, expected }) => {
            expectFullList().flush({ count: total, results: listed });
            expectUnfinishedCheck().flush(page(...listed.filter(isUnfinishedTransferJob)));

            expect(store.hasClearableJobs()).toBe(expected);
        });
    });
});
