import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { CUSTOM_ELEMENTS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';
import { EMPTY, Observable, Subject } from 'rxjs';

import { ImportResult } from '../../../../core/models/import-result.model';
import {
    ImportReviewDialogCloseResult,
    ImportReviewDialogData,
    ReviewItem,
} from '../../../../core/models/review-item.model';
import { TransferJob } from '../../../../core/models/transfer-job.model';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { storedZip } from '../../../../shared/utils/read-export-envelope.testing';
import { FilesSearchService } from '../../../files/services/files-search.service';
import { ImportResultDialogComponent } from '../../../flows/components/import-result-dialog/import-result-dialog.component';
import { ImportReviewDialogComponent } from '../../../flows/components/import-review-dialog/import-review-dialog.component';
import { CollectionStatus, GetCollectionRequest } from '../../models/collection.model';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { KnowledgeSourcesPollingService } from '../../services/knowledge-sources-polling.service';
import { CollectionsListPageComponent } from './collections-list-page.component';
import { CollectionDetailsComponent } from './components/collection-details/collection-details.component';

const COLLECTIONS_URL = '/api/source-collections/';
const EXPORT_JOBS_URL = '/api/source-collections/export-jobs/';
const IMPORT_JOBS_URL = '/api/source-collections/import-jobs/';
const INSPECT_URL = '/api/source-collections/import/inspect/';
const JOB_URL = '/api/transfer-jobs/job-1/';
const TICKET_URL = '/api/transfer-jobs/job-1/download-ticket/';
const DOWNLOAD_URL = '/api/transfer-jobs/job-1/download/?ticket=t-1';

function collection(id: number, name: string, createdAt: string): GetCollectionRequest {
    return {
        collection_id: id,
        collection_name: name,
        description: null,
        status: CollectionStatus.EMPTY,
        document_count: 0,
        rag_configurations: [],
        created_at: createdAt,
        updated_at: createdAt,
        created_by: null,
        last_edited_by: null,
        last_edited_at: null,
    };
}

// Newest first, as the list shows them.
const MANUALS = collection(1, 'Manuals', '2026-11-02T10:00:00Z');
const POLICIES = collection(2, 'Policies', '2026-11-01T10:00:00Z');
const IMPORTED = collection(3, 'Imported handbook', '2026-11-06T10:00:00Z');

const IMPORT_SUMMARY: ImportResult = {
    SourceCollection: {
        total: 1,
        created: { count: 1, items: [{ id: 3, name: 'Imported handbook' }] },
        reused: { count: 0, items: [] },
    },
};

function transferJob(overrides: Partial<TransferJob>): TransferJob {
    return {
        id: 'job-1',
        kind: 'export',
        main_entity: 'SourceCollection',
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

let httpMock: HttpTestingController;
let fixture: ComponentFixture<CollectionsListPageComponent>;
let dialogOpen: ReturnType<typeof vi.fn>;
let toastError: ReturnType<typeof vi.fn>;
let toastWarning: ReturnType<typeof vi.fn>;
let toastShow: ReturnType<typeof vi.fn>;
let toastRemove: ReturnType<typeof vi.fn>;
let clickedLinks: string[];

// jsdom has no ResizeObserver; the buttons' collapse-on-overflow only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

/** Renders the Knowledge Sources list with these collections, for a user granted these actions. */
function renderPage(
    collections: GetCollectionRequest[],
    granted: ActionCode[] = [ActionCode.Read, ActionCode.Create, ActionCode.Update, ActionCode.Export]
): void {
    vi.stubGlobal('ResizeObserver', ResizeObserverStub);
    dialogOpen = vi.fn(() => ({ closed: EMPTY }));
    toastError = vi.fn();
    toastWarning = vi.fn();
    toastShow = vi.fn(() => 1);
    toastRemove = vi.fn();
    clickedLinks = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
        clickedLinks.push(this.href);
    });
    const can = (resource: ResourceCode, action: ActionCode): boolean =>
        resource === ResourceCode.KnowledgeSources && granted.includes(action);

    TestBed.configureTestingModule({
        providers: [
            provideRouter([]),
            provideHttpClient(),
            provideHttpClientTesting(),
            FilesSearchService,
            { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            {
                provide: PermissionsService,
                useValue: {
                    can,
                    canAny: (resource: ResourceCode, actions: ActionCode[]) =>
                        actions.some((action) => can(resource, action)),
                },
            },
            { provide: Dialog, useValue: { open: dialogOpen } },
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
            // Polls collection details every few seconds; not what is under test.
            { provide: KnowledgeSourcesPollingService, useValue: { startPagePolling() {}, stopPagePolling() {} } },
        ],
    });
    // The open collection's panel brings its own services; the list beside it is under test.
    TestBed.overrideComponent(CollectionsListPageComponent, {
        remove: { imports: [CollectionDetailsComponent] },
        add: { schemas: [CUSTOM_ELEMENTS_SCHEMA] },
    });
    httpMock = TestBed.inject(HttpTestingController);
    // Already loaded once, as after a visit to the page: the list then shows without the first load's delay.
    TestBed.inject(CollectionsStorageService).setCollections(collections);

    fixture = TestBed.createComponent(CollectionsListPageComponent);
    fixture.detectChanges();
    httpMock.expectOne(COLLECTIONS_URL).flush(collections);
}

async function settle(): Promise<void> {
    await vi.waitFor(() => {
        fixture.detectChanges();
        expect(host().querySelector('app-collections-list-sidebar')).not.toBeNull();
    });
}

function host(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
}

function buttonLabelled(label: string): HTMLButtonElement | undefined {
    return [...host().querySelectorAll('button')].find(
        (button) => button.getAttribute('aria-label') === label || button.textContent?.trim() === label
    );
}

function click(label: string): void {
    const button = buttonLabelled(label);
    expect(button, `a "${label}" button`).toBeDefined();
    button!.click();
    fixture.detectChanges();
}

function cardNamed(name: string): HTMLElement {
    const card = [...host().querySelectorAll<HTMLElement>('app-collection')].find((candidate) =>
        candidate.textContent?.includes(name)
    );
    expect(card, `a "${name}" card`).toBeDefined();
    return card!;
}

function shownCollectionNames(): string[] {
    return [...host().querySelectorAll('app-collection .name')].map((name) => name.textContent!.trim());
}

/** Lets the export job finish and hands out its download link. */
async function completeExportJob(): Promise<void> {
    (await vi.waitFor(() => httpMock.expectOne(JOB_URL))).flush(
        transferJob({ status: 'completed', file_name: 'collections.zip', result: { excluded: [] } })
    );
    httpMock.expectOne(TICKET_URL).flush({ download_url: DOWNLOAD_URL });
}

afterEach(() => {
    httpMock.verify();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
});

describe('CollectionsListPageComponent export', () => {
    it('exports a collection from its card as a job and downloads the archive through a ticket', async () => {
        renderPage([MANUALS, POLICIES]);
        await settle();

        click('Export Policies');

        const start = httpMock.expectOne(EXPORT_JOBS_URL);
        expect(start.request.body).toEqual({ ids: [2] });
        start.flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        await completeExportJob();

        expect(clickedLinks).toEqual([new URL(DOWNLOAD_URL, document.baseURI).href]);
        expect(toastError).not.toHaveBeenCalled();
        // The export button does not open the collection.
        expect(cardNamed('Policies').querySelector('.collection.selected')).toBeNull();
    });

    it('exports every picked collection in one job', async () => {
        renderPage([MANUALS, POLICIES]);
        await settle();

        click('Select');
        cardNamed('Manuals').click();
        cardNamed('Policies').click();
        fixture.detectChanges();
        click('Export');

        const start = httpMock.expectOne(EXPORT_JOBS_URL);
        expect(start.request.body).toEqual({ ids: [1, 2] });
        start.flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        await completeExportJob();

        expect(clickedLinks).toHaveLength(1);
    });

    it("disables a card's Export while its export runs, so a second click starts no second job", async () => {
        renderPage([MANUALS, POLICIES]);
        await settle();

        click('Export Policies');
        httpMock.expectOne(EXPORT_JOBS_URL).flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        fixture.detectChanges();

        expect(buttonLabelled('Export Policies')!.disabled).toBe(true);
        expect(buttonLabelled('Export Manuals')!.disabled).toBe(false);
        buttonLabelled('Export Policies')!.click();
        httpMock.expectNone(EXPORT_JOBS_URL);

        await completeExportJob();
        fixture.detectChanges();
        expect(buttonLabelled('Export Policies')!.disabled).toBe(false);
    });

    it("reports a failed export job with the server's reason and downloads nothing", async () => {
        renderPage([MANUALS]);
        await settle();

        click('Export Manuals');
        httpMock.expectOne(EXPORT_JOBS_URL).flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        (await vi.waitFor(() => httpMock.expectOne(JOB_URL))).flush(
            transferJob({ status: 'failed', error: { code: 'export_failed', message: 'Storage is unavailable.' } })
        );

        expect(toastError).toHaveBeenCalledExactlyOnceWith('Storage is unavailable.');
        expect(clickedLinks).toEqual([]);
    });
});

describe('CollectionsListPageComponent bulk selection', () => {
    const PROCEDURES = collection(4, 'Procedures', '2026-10-31T10:00:00Z');

    function search(term: string): void {
        TestBed.inject(FilesSearchService).setSearchTerm(term);
        fixture.detectChanges();
    }

    /** The "Select All" / "Deselect All" item of the Select menu, which opens in an overlay. */
    function clickSelectMenuItem(label: 'Select All' | 'Deselect All'): void {
        click(buttonLabelled('Select') ? 'Select' : `Selected (${selectedCount()})`);
        const item = [...document.querySelectorAll<HTMLButtonElement>('.bulk-select-menu__item')].find(
            (candidate) => candidate.textContent?.trim() === label
        );
        expect(item, `a "${label}" menu item`).toBeDefined();
        item!.click();
        fixture.detectChanges();
    }

    function selectedCount(): number {
        const count = host().querySelector('.bulk-select__count')?.textContent ?? '(0)';
        return Number(count.replace(/[()]/g, ''));
    }

    it('selects all shown collections without dropping a pick the search hides', async () => {
        renderPage([MANUALS, POLICIES, PROCEDURES]);
        await settle();
        click('Select');
        cardNamed('Manuals').click();
        fixture.detectChanges();

        search('P');
        clickSelectMenuItem('Select All');
        // Manuals is picked but hidden: neither counted nor exported.
        expect(selectedCount()).toBe(2);

        search('');
        expect(selectedCount()).toBe(3);
    });

    it('deselects only the shown collections', async () => {
        renderPage([MANUALS, POLICIES, PROCEDURES]);
        await settle();
        click('Select');
        cardNamed('Manuals').click();
        cardNamed('Policies').click();
        fixture.detectChanges();

        search('Pol');
        clickSelectMenuItem('Deselect All');
        search('');

        expect(selectedCount()).toBe(1);
        click('Export');
        expect(httpMock.expectOne(EXPORT_JOBS_URL).request.body).toEqual({ ids: [1] });
    });

    it('exports only the picks the list shows', async () => {
        renderPage([MANUALS, POLICIES, PROCEDURES]);
        await settle();
        click('Select');
        cardNamed('Manuals').click();
        cardNamed('Policies').click();
        fixture.detectChanges();

        search('Pol');
        click('Export');

        expect(httpMock.expectOne(EXPORT_JOBS_URL).request.body).toEqual({ ids: [2] });
    });
});

describe('CollectionsListPageComponent permissions', () => {
    it('offers no export, on a card or for a selection, without the export permission', async () => {
        renderPage([MANUALS], [ActionCode.Read, ActionCode.Create, ActionCode.Update]);
        await settle();

        expect(buttonLabelled('Export Manuals')).toBeUndefined();
        expect(buttonLabelled('Select')).toBeUndefined();
        expect(buttonLabelled('Import')).toBeDefined();
    });

    it('offers no import without the create permission', async () => {
        renderPage([MANUALS], [ActionCode.Read, ActionCode.Export]);
        await settle();

        expect(buttonLabelled('Import')).toBeUndefined();
        expect(buttonLabelled('Export Manuals')).toBeDefined();
    });
});

describe('CollectionsListPageComponent import', () => {
    // The page loads the zip reader on demand; loaded here, its first load does not eat into a test's time limit.
    beforeAll(() => import('@zip.js/zip.js'));

    /** Clicks Import and picks the file in the browser's file picker (a detached <input type="file">). */
    function chooseFileToImport(file: File): void {
        const picker = document.createElement('input');
        vi.spyOn(picker, 'click').mockImplementation(() => undefined);
        const createElement = vi.spyOn(document, 'createElement').mockReturnValueOnce(picker);
        click('Import');
        createElement.mockRestore();
        Object.defineProperty(picker, 'files', { value: [file] });
        picker.dispatchEvent(new Event('change'));
    }

    const ENVELOPE = { main_entity: 'SourceCollection', version: 6 };
    const CODE_TO_REVIEW: ReviewItem = { kind: 'mcp_tool', name: 'Search', transport: 'stdio' };

    function archiveToImport(): File {
        return storedZip('collections.zip', {
            'export.json': JSON.stringify(ENVELOPE),
            'files/collection-3/handbook.pdf': '%PDF',
        });
    }

    /** Picks the archive and waits for its inspection, which gets only the archive's envelope. */
    async function chooseArchiveAndInspect(archive: File): Promise<TestRequest> {
        chooseFileToImport(archive);
        const inspect = await vi.waitFor(() => httpMock.expectOne(INSPECT_URL));
        const inspected = (inspect.request.body as FormData).get('file') as File;
        expect(inspected).not.toBe(archive);
        expect(JSON.parse(await inspected.text())).toEqual(ENVELOPE);
        return inspect;
    }

    function uploadArchive(archive: File): void {
        const upload = httpMock.expectOne((request) => request.url === IMPORT_JOBS_URL);
        expect(upload.request.body).toBe(archive);
        upload.flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
    }

    /** Picks an archive, passes its inspection with nothing to review and starts its import job. */
    async function startArchiveImport(): Promise<void> {
        const archive = archiveToImport();
        (await chooseArchiveAndInspect(archive)).flush({ review_items: [] });
        uploadArchive(archive);
    }

    async function finishImportJob(job: TransferJob): Promise<void> {
        (await vi.waitFor(() => httpMock.expectOne(JOB_URL))).flush(job);
    }

    it('imports an archive as a job, shows the result and lists the imported collection', async () => {
        renderPage([MANUALS]);
        await settle();

        await startArchiveImport();
        await finishImportJob(transferJob({ kind: 'import', status: 'completed', result: IMPORT_SUMMARY }));

        expect(dialogOpen).toHaveBeenCalledWith(
            ImportResultDialogComponent,
            expect.objectContaining({ data: { importResult: IMPORT_SUMMARY } })
        );
        httpMock.expectOne(COLLECTIONS_URL).flush([IMPORTED, MANUALS]);
        await vi.waitFor(() => {
            fixture.detectChanges();
            expect(shownCollectionNames()).toEqual(['Imported handbook', 'Manuals']);
        });
        expect(toastError).not.toHaveBeenCalled();
    });

    it('shows its progress from the inspection until the import has finished', async () => {
        renderPage([MANUALS]);
        await settle();

        const archive = archiveToImport();
        const inspect = await chooseArchiveAndInspect(archive);
        expect(toastShow).toHaveBeenCalledExactlyOnceWith('Importing…', 'info', expect.any(Number));
        inspect.flush({ review_items: [] });
        uploadArchive(archive);
        expect(toastRemove).not.toHaveBeenCalled();

        await finishImportJob(transferJob({ kind: 'import', status: 'completed', result: IMPORT_SUMMARY }));

        expect(toastRemove).toHaveBeenCalledOnce();
        httpMock.expectOne(COLLECTIONS_URL).flush([IMPORTED, MANUALS]);
    });

    it('says so, instead of showing an empty result, when the finished import reports no summary', async () => {
        renderPage([MANUALS]);
        await settle();

        await startArchiveImport();
        await finishImportJob(transferJob({ kind: 'import', status: 'completed', result: null }));

        expect(toastWarning).toHaveBeenCalledExactlyOnceWith(
            'The import has finished, but the server did not report what it brought in. Check the list for the new items.'
        );
        expect(dialogOpen).not.toHaveBeenCalled();
        httpMock.expectOne(COLLECTIONS_URL).flush([IMPORTED, MANUALS]);
    });

    it('stops waiting for the import job when the page is left', async () => {
        renderPage([MANUALS]);
        await settle();

        await startArchiveImport();
        const poll = await vi.waitFor(() => httpMock.expectOne(JOB_URL));
        fixture.destroy();

        expect(poll.cancelled).toBe(true);
        expect(toastRemove).toHaveBeenCalledOnce();
        await new Promise((resolve) => setTimeout(resolve, 2_500));
        httpMock.expectNone(JOB_URL);
    });

    describe('with code to review', () => {
        let reviewClosed: Subject<ImportReviewDialogCloseResult>;

        /** Picks an archive whose inspection finds code to review; returns what the review dialog is given. */
        async function openReview(archive: File): Promise<ImportReviewDialogData> {
            reviewClosed = new Subject();
            dialogOpen.mockReturnValueOnce({ closed: reviewClosed });
            (await chooseArchiveAndInspect(archive)).flush({ review_items: [CODE_TO_REVIEW] });

            expect(dialogOpen).toHaveBeenCalledWith(ImportReviewDialogComponent, expect.anything());
            httpMock.expectNone((request) => request.url === IMPORT_JOBS_URL);
            // The dialog shows its own progress: the toast ends with the inspection.
            expect(toastRemove).toHaveBeenCalledOnce();
            return dialogOpen.mock.calls[0][1].data as ImportReviewDialogData;
        }

        function collect(source: Observable<unknown>): unknown[] {
            const values: unknown[] = [];
            source.subscribe((value) => values.push(value));
            return values;
        }

        it("imports the archive when the review dialog's Import is pressed and shows the result", async () => {
            renderPage([MANUALS]);
            await settle();
            const archive = archiveToImport();
            const review = await openReview(archive);
            expect(review.reviewItems).toEqual([CODE_TO_REVIEW]);

            const imported = collect(review.importFn());
            uploadArchive(archive);
            await finishImportJob(transferJob({ kind: 'import', status: 'completed', result: IMPORT_SUMMARY }));
            expect(imported).toEqual([IMPORT_SUMMARY]);
            reviewClosed.next({ action: 'imported', result: IMPORT_SUMMARY });

            expect(dialogOpen).toHaveBeenLastCalledWith(
                ImportResultDialogComponent,
                expect.objectContaining({ data: { importResult: IMPORT_SUMMARY } })
            );
            httpMock.expectOne(COLLECTIONS_URL).flush([IMPORTED, MANUALS]);
        });

        it('imports nothing when the review is cancelled', async () => {
            renderPage([MANUALS]);
            await settle();
            await openReview(archiveToImport());

            reviewClosed.next({ action: 'cancel' });

            expect(dialogOpen).toHaveBeenCalledOnce();
            httpMock.expectNone((request) => request.url === IMPORT_JOBS_URL);
            httpMock.expectNone(COLLECTIONS_URL);
        });
    });

    it("reports a failed import job with the server's reason and leaves the list as it was", async () => {
        renderPage([MANUALS]);
        await settle();

        await startArchiveImport();
        await finishImportJob(
            transferJob({
                kind: 'import',
                status: 'failed',
                error: { code: 'invalid_archive', message: 'handbook.pdf is missing.' },
            })
        );

        expect(toastError).toHaveBeenCalledExactlyOnceWith('handbook.pdf is missing.');
        expect(dialogOpen).not.toHaveBeenCalled();
        httpMock.expectNone(COLLECTIONS_URL);
    });

    it('refuses a plain JSON export without uploading it, as only an archive carries the files', async () => {
        renderPage([MANUALS]);
        await settle();

        chooseFileToImport(new File([JSON.stringify({ main_entity: 'SourceCollection' })], 'collections.json'));

        await vi.waitFor(() =>
            expect(toastError).toHaveBeenCalledExactlyOnceWith(
                'Knowledge sources are imported from a .zip export. Choose a .zip file.'
            )
        );
        httpMock.expectNone(INSPECT_URL);
    });
});
