import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../services/config';
import { ToastService } from '../../services/notifications';
import { TransferJob } from '../models/transfer-job.model';
import { TransferExportService } from './transfer-export.service';

const EXPORT_JOBS_URL = '/api/source-collections/export-jobs/';
const JOB_URL = '/api/transfer-jobs/job-1/';

function completedExport(): TransferJob {
    return {
        id: 'job-1',
        kind: 'export',
        main_entity: 'SourceCollection',
        status: 'completed',
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
