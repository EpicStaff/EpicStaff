import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../services/config';
import { ToastService } from '../../services/notifications';
import { TransferJob } from '../models/transfer-job.model';
import { TransferExportService } from './transfer-export.service';
import { TransferJobsService } from './transfer-jobs.service';

const EXPORT_JOBS_URL = '/api/source-collections/export-jobs/';
const JOB_URL = '/api/transfer-jobs/job-1/';

function completedExport(): TransferJob {
    return {
        id: 'job-1',
        kind: 'export',
        main_entity: 'SourceCollection',
        status: 'completed',
        display_name: 'Handbook',
        file_name: 'collections.zip',
        result: { excluded: [] },
        error: null,
        created_at: '2026-11-06T10:00:00Z',
        finished_at: '2026-11-06T10:01:00Z',
        expires_at: null,
    };
}

describe('TransferExportService collection exports', () => {
    let service: TransferExportService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                {
                    provide: ToastService,
                    useValue: { show: () => 1, remove: vi.fn(), error: vi.fn(), warning: vi.fn() },
                },
            ],
        });
        service = TestBed.inject(TransferExportService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        httpMock.verify();
        vi.restoreAllMocks();
    });

    async function finishExport(): Promise<void> {
        httpMock.expectOne(EXPORT_JOBS_URL).flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        (await vi.waitFor(() => httpMock.expectOne(JOB_URL))).flush(completedExport());
        httpMock
            .expectOne('/api/transfer-jobs/job-1/download-ticket/')
            .flush({ download_url: '/api/transfer-jobs/job-1/download/?ticket=t-1' });
    }

    it('starts no second job for collections whose export is still running', async () => {
        service.exportCollections([4]).subscribe();
        expect([...service.exportingCollectionIds()]).toEqual([4]);

        service.exportCollections([4]).subscribe();

        await finishExport();
        expect([...service.exportingCollectionIds()]).toEqual([]);
    });

    it('exports a collection again once its export has finished', async () => {
        service.exportCollections([4]).subscribe();
        await finishExport();

        service.exportCollections([4]).subscribe();

        httpMock.expectOne(EXPORT_JOBS_URL);
    });

    it('still exports a selection that adds collections to one already running', async () => {
        service.exportCollections([4]).subscribe();
        httpMock.expectOne(EXPORT_JOBS_URL);

        service.exportCollections([4, 5]).subscribe();

        expect(httpMock.match(EXPORT_JOBS_URL).map((request) => request.request.body)).toEqual([{ ids: [4, 5] }]);
        expect([...service.exportingCollectionIds()]).toEqual([4, 5]);
    });
});

describe('TransferExportService export of any start', () => {
    let service: TransferExportService;
    let transferJobs: TransferJobsService;
    let httpMock: HttpTestingController;
    let toastError: ReturnType<typeof vi.fn>;
    let clicks: string[];

    beforeEach(() => {
        clicks = [];
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
            clicks.push(this.href);
        });
        toastError = vi.fn();
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                {
                    provide: ToastService,
                    useValue: { show: () => 1, remove: vi.fn(), error: toastError, warning: vi.fn() },
                },
            ],
        });
        service = TestBed.inject(TransferExportService);
        transferJobs = TestBed.inject(TransferJobsService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        httpMock.verify();
        vi.restoreAllMocks();
    });

    it('downloads the archive of the job the start began once it is ready', async () => {
        const finished: TransferJob[] = [];
        service
            .export(transferJobs.startExport('pythonCodeTools', { ids: [3] }))
            .subscribe((job) => finished.push(job));

        httpMock
            .expectOne('/api/python-code-tool/export-jobs/')
            .flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        (await vi.waitFor(() => httpMock.expectOne(JOB_URL))).flush({
            ...completedExport(),
            main_entity: 'PythonCodeTool',
            file_name: 'tools.zip',
        });
        httpMock
            .expectOne('/api/transfer-jobs/job-1/download-ticket/')
            .flush({ download_url: '/api/transfer-jobs/job-1/download/?ticket=t-1' });

        expect(clicks).toEqual([expect.stringContaining('/api/transfer-jobs/job-1/download/?ticket=t-1')]);
        expect(finished.map((job) => job.id)).toEqual(['job-1']);
    });

    it.each([
        [
            'too many unfinished jobs',
            429,
            { status_code: 429, code: 'too_many_jobs', message: 'You already have 3 unfinished exports.' },
        ],
        [
            'items that are gone or in another organization',
            404,
            { status_code: 404, code: 'export_entities_not_found', message: 'Some entity IDs do not exist' },
        ],
    ])(
        'shows the reason the server refused to start the export (%s), and completes without a value',
        (_case, status, body) => {
            let completed = false;
            const finished: TransferJob[] = [];
            service.export(transferJobs.startExport('mcpTools', { ids: [4] })).subscribe({
                next: (job) => finished.push(job),
                complete: () => (completed = true),
            });

            httpMock.expectOne('/api/mcp-tools/export-jobs/').flush(body, { status, statusText: 'Refused' });

            expect(toastError.mock.calls.map(([message]) => message)).toEqual([body.message]);
            expect(finished).toEqual([]);
            expect(completed).toBe(true);
        }
    );
});
