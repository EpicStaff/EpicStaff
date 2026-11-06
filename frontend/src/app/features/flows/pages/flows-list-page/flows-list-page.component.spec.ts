import { Dialog } from '@angular/cdk/dialog';
import { OverlayContainer } from '@angular/cdk/overlay';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { CUSTOM_ELEMENTS_SCHEMA, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ConfirmationDialogService, LabelSidebarComponent, SearchComponent } from '@shared/components';
import { EXPORT_WARNING_DURATION_MS } from '@shared/constants';
import { AppStorageService } from '@shared/services';
import { EMPTY, Observable } from 'rxjs';

import { EntityTypeResult, FlowImportResultItem, ImportResult } from '../../../../core/models/import-result.model';
import { ImportReviewDialogData, ReviewItem } from '../../../../core/models/review-item.model';
import { TransferJob } from '../../../../core/models/transfer-job.model';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { RecycleBinSettingsService } from '../../../../services/recycle-bin';
import { storedZip } from '../../../../shared/utils/read-export-envelope.testing';
import { FlowsFilterMenuComponent } from '../../components/filter/flows-filter-menu/flows-filter-menu.component';
import { ImportFlowOptionsPopoverComponent } from '../../components/import-flow-options-popover/import-flow-options-popover.component';
import { ImportResultDialogComponent } from '../../components/import-result-dialog/import-result-dialog.component';
import { ImportReviewDialogComponent } from '../../components/import-review-dialog/import-review-dialog.component';
import { EMPTY_FLOWS_FILTER } from '../../models/flow-filter.model';
import { FlowsStorageService } from '../../services/flows-storage.service';
import { LabelsStorageService } from '../../services/labels-storage.service';
import { FlowsListPageComponent } from './flows-list-page.component';

const INSPECT_URL = '/api/graphs/import/inspect/';
const IMPORT_URL = '/api/graphs/import/';
const IMPORT_JOBS_URL = '/api/graphs/import-jobs/';
const SUMMARY: ImportResult = {
    Flow: { total: 1, created: { count: 1, items: [{ id: 3, name: 'Orders' }] }, reused: { count: 0, items: [] } },
};
const CODE_TO_REVIEW: ReviewItem = { kind: 'mcp_tool', name: 'Search', transport: 'stdio' };
const REFUSAL_BODY = {
    status_code: 403,
    code: 'flow_with_trigger_nodes_requires_use_permission',
    message: 'This flow contains trigger nodes.',
};
const IMPORT_REFUSAL_WARNING = {
    title: 'Use permission required',
    message: 'This file contains trigger nodes (Webhook, Telegram, Schedule).',
    caution: '<strong>Importing</strong> it requires the <strong>Use</strong> permission on flows.',
    type: 'warning',
    hideConfirm: true,
    cancelText: 'OK',
};

function transferJob(overrides: Partial<TransferJob>): TransferJob {
    return {
        id: 'job-1',
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

// jsdom has no ResizeObserver; the overflow directives in the header only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

let dialogOpen: ReturnType<typeof vi.fn>;
let confirm: ReturnType<typeof vi.fn>;
let toastError: ReturnType<typeof vi.fn>;
let toastWarning: ReturnType<typeof vi.fn>;
let toastShow: ReturnType<typeof vi.fn>;
let toastRemove: ReturnType<typeof vi.fn>;
let httpMock: HttpTestingController;
let fixture: ComponentFixture<FlowsListPageComponent>;

/** Renders the page header; in select mode, with these flows picked, when any are given. */
function renderPage(selectedFlowIds: number[] = []): void {
    vi.stubGlobal('ResizeObserver', ResizeObserverStub);
    dialogOpen = vi.fn(() => ({ closed: EMPTY }));
    confirm = vi.fn();
    toastError = vi.fn();
    toastWarning = vi.fn();
    toastShow = vi.fn(() => 1);
    toastRemove = vi.fn();

    TestBed.configureTestingModule({
        providers: [
            provideRouter([]),
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            { provide: PermissionsService, useValue: { can: () => true, canAny: () => true } },
            { provide: Dialog, useValue: { open: dialogOpen } },
            { provide: ConfirmationDialogService, useValue: { confirm } },
            {
                provide: ToastService,
                useValue: {
                    error: toastError,
                    warning: toastWarning,
                    success: vi.fn(),
                    show: toastShow,
                    remove: toastRemove,
                },
            },
            { provide: AppStorageService, useValue: { invalidate: vi.fn() } },
            { provide: RecycleBinSettingsService, useValue: { retentionDays: signal(7) } },
            {
                provide: FlowsStorageService,
                useValue: {
                    selectMode: signal(selectedFlowIds.length > 0),
                    selectedFlowIds: signal(selectedFlowIds),
                    isDeleting: signal(false),
                    isAllFlowsSelected: () => false,
                    filter: signal(EMPTY_FLOWS_FILTER),
                    flows: signal([]),
                    getFlows: () => EMPTY,
                    setFilter: vi.fn(),
                    resetFilter: vi.fn(),
                    setSelectMode: vi.fn(),
                },
            },
            {
                provide: LabelsStorageService,
                useValue: {
                    activeLabelFilter: signal('all'),
                    labels: signal([]),
                    setActiveLabelFilter: vi.fn(),
                    loadLabels: () => EMPTY,
                },
            },
        ],
    });
    // The header with its Import button is under test; these children bring their own services.
    TestBed.overrideComponent(FlowsListPageComponent, {
        remove: {
            imports: [
                LabelSidebarComponent,
                SearchComponent,
                FlowsFilterMenuComponent,
                ImportFlowOptionsPopoverComponent,
            ],
        },
        add: { schemas: [CUSTOM_ELEMENTS_SCHEMA] },
    });
    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(FlowsListPageComponent);
    fixture.detectChanges();
}

describe('FlowsListPageComponent flow import', () => {
    let file: File;

    beforeEach(() => {
        file = new File(['{}'], 'flow.json');
        renderPage();
    });

    afterEach(() => {
        httpMock.verify();
        vi.unstubAllGlobals();
    });

    /** Clicks Import and picks the file in the browser's file picker (a detached <input type="file">). */
    async function chooseFileToImport(): Promise<TestRequest> {
        const picker = document.createElement('input');
        vi.spyOn(picker, 'click').mockImplementation(() => undefined);
        const createElement = vi.spyOn(document, 'createElement').mockReturnValueOnce(picker);
        (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.import-group__main')!.click();
        createElement.mockRestore();
        Object.defineProperty(picker, 'files', { value: [file] });
        picker.dispatchEvent(new Event('change'));
        // The file is read asynchronously before it is inspected.
        return vi.waitFor(() => httpMock.expectOne(INSPECT_URL));
    }

    async function importFileWithoutCodeToReview(): Promise<TestRequest> {
        (await chooseFileToImport()).flush({ review_items: [] });
        const request = httpMock.expectOne(IMPORT_URL);
        expect(request.request.method).toBe('POST');
        expect((request.request.body as FormData).get('file')).toBe(file);
        return request;
    }

    it('imports the file and shows the result', async () => {
        (await importFileWithoutCodeToReview()).flush(SUMMARY);

        expect(dialogOpen).toHaveBeenCalledWith(
            ImportResultDialogComponent,
            expect.objectContaining({ data: { importResult: SUMMARY } })
        );
        expect(confirm).not.toHaveBeenCalled();
        expect(toastError).not.toHaveBeenCalled();
    });

    describe('by export version', () => {
        const FLOW_IN_FILE = { id: 3, name: 'Orders', description: 'Daily orders' };
        // The summary's flow, with the description the import file gives it.
        const ENRICHED_FLOWS: EntityTypeResult<FlowImportResultItem> = {
            total: 1,
            created: { count: 1, items: [{ id: 3, name: 'Orders', description: 'Daily orders' }] },
            reused: { count: 0, items: [] },
        };
        const ENRICHED_SUMMARY: ImportResult = { Flow: ENRICHED_FLOWS };

        it('imports a version 5 export file with the synchronous import', async () => {
            const envelope = { main_entity: 'Flow', version: 5, Flow: [FLOW_IN_FILE] };
            file = new File([JSON.stringify(envelope)], 'flow.json');

            (await importFileWithoutCodeToReview()).flush(SUMMARY);

            expect(dialogOpen).toHaveBeenCalledWith(
                ImportResultDialogComponent,
                expect.objectContaining({ data: { importResult: ENRICHED_SUMMARY } })
            );
            httpMock.expectNone((request) => request.url === IMPORT_JOBS_URL);
        });

        it('imports a version 6 archive as a background job and shows its result', async () => {
            const envelope = { main_entity: 'Flow', version: 6, Flow: [FLOW_IN_FILE] };
            file = storedZip('flows.zip', {
                'export.json': JSON.stringify(envelope),
                'files/collection-1/manual.pdf': '%PDF',
            });

            const inspect = await chooseFileToImport();
            // Only the envelope is inspected: the archive is uploaded once, by the import job.
            const inspected = (inspect.request.body as FormData).get('file') as File;
            expect(inspected).not.toBe(file);
            expect(JSON.parse(await inspected.text())).toEqual(envelope);
            expect(toastShow).toHaveBeenCalledExactlyOnceWith('Importing…', 'info', expect.any(Number));
            inspect.flush({ review_items: [] });
            httpMock.expectNone(IMPORT_URL);
            const upload = httpMock.expectOne((request) => request.url === IMPORT_JOBS_URL);
            expect(upload.request.body).toBe(file);
            upload.flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
            expect(toastRemove).not.toHaveBeenCalled();

            const poll = await vi.waitFor(() => httpMock.expectOne('/api/transfer-jobs/job-1/'));
            poll.flush(transferJob({ kind: 'import', status: 'completed', result: SUMMARY }));

            expect(dialogOpen).toHaveBeenCalledWith(
                ImportResultDialogComponent,
                expect.objectContaining({ data: { importResult: ENRICHED_SUMMARY } })
            );
            expect(toastRemove).toHaveBeenCalled();
            expect(toastError).not.toHaveBeenCalled();
        });

        it('says so, instead of showing an empty result, when the finished import job reports no summary', async () => {
            file = storedZip('flows.zip', { 'export.json': JSON.stringify({ main_entity: 'Flow', version: 6 }) });

            (await chooseFileToImport()).flush({ review_items: [] });
            httpMock
                .expectOne((request) => request.url === IMPORT_JOBS_URL)
                .flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
            const poll = await vi.waitFor(() => httpMock.expectOne('/api/transfer-jobs/job-1/'));
            poll.flush(transferJob({ kind: 'import', status: 'completed', result: null }));

            expect(toastWarning).toHaveBeenCalledExactlyOnceWith(
                'The import has finished, but the server did not report what it brought in. Check the list for the new items.'
            );
            expect(dialogOpen).not.toHaveBeenCalled();
        });

        it("reports a failed import job with the server's reason", async () => {
            file = storedZip('flows.zip', { 'export.json': JSON.stringify({ main_entity: 'Flow', version: 6 }) });

            (await chooseFileToImport()).flush({ review_items: [] });
            httpMock
                .expectOne((request) => request.url === IMPORT_JOBS_URL)
                .flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
            const poll = await vi.waitFor(() => httpMock.expectOne('/api/transfer-jobs/job-1/'));
            poll.flush(
                transferJob({
                    kind: 'import',
                    status: 'failed',
                    error: { code: 'invalid_archive', message: 'manual.pdf is missing.' },
                })
            );

            expect(toastError).toHaveBeenCalledExactlyOnceWith('manual.pdf is missing.');
            expect(dialogOpen).not.toHaveBeenCalled();
        });
    });

    it('explains an import refused over trigger nodes in the Use permission warning, with no toast and no result', async () => {
        (await importFileWithoutCodeToReview()).flush(REFUSAL_BODY, { status: 403, statusText: 'Forbidden' });

        expect(confirm).toHaveBeenCalledExactlyOnceWith(IMPORT_REFUSAL_WARNING);
        expect(dialogOpen).not.toHaveBeenCalled();
        expect(toastError).not.toHaveBeenCalled();
    });

    it('reports any other import failure with the reason the backend gave', async () => {
        (await importFileWithoutCodeToReview()).flush(
            { message: 'Bad file' },
            { status: 400, statusText: 'Bad Request' }
        );

        expect(toastError).toHaveBeenCalledExactlyOnceWith('Bad file');
        expect(confirm).not.toHaveBeenCalled();
        expect(dialogOpen).not.toHaveBeenCalled();
    });

    describe('with code to review', () => {
        async function openReview(): Promise<ImportReviewDialogData> {
            (await chooseFileToImport()).flush({ review_items: [CODE_TO_REVIEW] });
            expect(dialogOpen).toHaveBeenCalledWith(ImportReviewDialogComponent, expect.anything());
            httpMock.expectNone(IMPORT_URL);
            return dialogOpen.mock.calls[0][1].data as ImportReviewDialogData;
        }

        function collect(source: Observable<unknown>): { values: unknown[]; completed: boolean } {
            const outcome = { values: [] as unknown[], completed: false };
            source.subscribe({
                next: (value) => outcome.values.push(value),
                complete: () => (outcome.completed = true),
            });
            return outcome;
        }

        it("imports the file when the review dialog's Import is pressed", async () => {
            const review = await openReview();

            const outcome = collect(review.importFn());
            httpMock.expectOne(IMPORT_URL).flush(SUMMARY);

            expect(outcome.values).toEqual([SUMMARY]);
        });

        it('explains a refusal over trigger nodes and gives the review dialog no result, so it stays open', async () => {
            const review = await openReview();

            const outcome = collect(review.importFn());
            httpMock.expectOne(IMPORT_URL).flush(REFUSAL_BODY, { status: 403, statusText: 'Forbidden' });

            expect(confirm).toHaveBeenCalledExactlyOnceWith(IMPORT_REFUSAL_WARNING);
            expect(outcome).toEqual({ values: [], completed: true });
        });
    });
});

describe('FlowsListPageComponent bulk export', () => {
    const clickedLinks: string[] = [];

    beforeEach(() => {
        clickedLinks.length = 0;
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
            clickedLinks.push(this.href);
        });
        renderPage([1, 2]);
    });

    afterEach(() => {
        httpMock.verify();
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    function clickButton(container: HTMLElement, label: string): void {
        const button = [...container.querySelectorAll('button')].find(
            (candidate) => candidate.textContent?.trim() === label
        );
        expect(button, `a "${label}" button`).toBeDefined();
        button!.click();
        fixture.detectChanges();
    }

    /** Clicks "Export 2 flows", then Export in the options it opens, leaving them as they open. */
    function exportSelectedFlows(): void {
        clickButton(fixture.nativeElement as HTMLElement, 'Export 2 flows');
        clickButton(TestBed.inject(OverlayContainer).getContainerElement(), 'Export');
    }

    it('exports the selected flows with their knowledge as a job, downloads the archive and warns about what was left out', async () => {
        exportSelectedFlows();

        const start = httpMock.expectOne('/api/graphs/export-jobs/');
        expect(start.request.body).toEqual({ ids: [1, 2], include_knowledge: true });
        expect(toastShow).toHaveBeenCalledWith('Preparing export…', 'info', expect.any(Number));
        start.flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });

        const poll = await vi.waitFor(() => httpMock.expectOne('/api/transfer-jobs/job-1/'));
        poll.flush(
            transferJob({
                status: 'completed',
                file_name: 'bulk_2.zip',
                result: { excluded: [{ entity_type: 'Flow', entity_id: 4, name: 'Child' }] },
            })
        );
        httpMock
            .expectOne('/api/transfer-jobs/job-1/download-ticket/')
            .flush({ download_url: '/api/transfer-jobs/job-1/download/?ticket=t-1' });

        expect(clickedLinks).toEqual([new URL('/api/transfer-jobs/job-1/download/?ticket=t-1', document.baseURI).href]);
        expect(toastWarning).toHaveBeenCalledWith(
            expect.stringContaining('1 subflow (Child)'),
            EXPORT_WARNING_DURATION_MS,
            undefined
        );
        expect(toastRemove).toHaveBeenCalled();
    });

    it("reports a failed export job with the server's reason and downloads nothing", async () => {
        exportSelectedFlows();

        httpMock
            .expectOne('/api/graphs/export-jobs/')
            .flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        const poll = await vi.waitFor(() => httpMock.expectOne('/api/transfer-jobs/job-1/'));
        poll.flush(
            transferJob({ status: 'failed', error: { code: 'export_failed', message: 'Storage is unavailable.' } })
        );

        expect(toastError).toHaveBeenCalledExactlyOnceWith('Storage is unavailable.');
        expect(clickedLinks).toEqual([]);
    });

    it('reports a refused start with the reason from the error envelope', () => {
        exportSelectedFlows();

        httpMock
            .expectOne('/api/graphs/export-jobs/')
            .flush(
                { status_code: 429, code: 'too_many_jobs', message: 'Too many exports are running. Try again later.' },
                { status: 429, statusText: 'Too Many Requests' }
            );

        expect(toastError).toHaveBeenCalledExactlyOnceWith('Too many exports are running. Try again later.');
        expect(clickedLinks).toEqual([]);
    });
});
