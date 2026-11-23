import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';
import { EMPTY, Observable, Subject } from 'rxjs';

import { ImportResult } from '../../../../core/models/import-result.model';
import {
    ImportReviewDialogCloseResult,
    ImportReviewDialogData,
    ReviewItem,
} from '../../../../core/models/review-item.model';
import { TransferJob } from '../../../../core/models/transfer-job.model';
import { TRANSFER_JOB_POLL_INTERVAL_MS } from '../../../../core/services/transfer-jobs.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { storedZip } from '../../../../shared/utils/read-export-envelope.testing';
import { ImportResultDialogComponent } from '../../../flows/components/import-result-dialog/import-result-dialog.component';
import { ImportReviewDialogComponent } from '../../../flows/components/import-review-dialog/import-review-dialog.component';
import { CollectionStatus, GetCollectionRequest } from '../../models/collection.model';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { CollectionsImportComponent } from './collections-import.component';

const COLLECTIONS_URL = '/api/source-collections/';
const IMPORT_JOBS_URL = '/api/source-collections/import-jobs/';
const INSPECT_URL = '/api/source-collections/import/inspect/';
const JOB_URL = '/api/transfer-jobs/job-1/';

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

const MANUALS = collection(1, 'Manuals', '2026-11-02T10:00:00Z');
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
        kind: 'import',
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
let fixture: ComponentFixture<CollectionsImportComponent>;
let dialogOpen: ReturnType<typeof vi.fn>;
let toastError: ReturnType<typeof vi.fn>;
let toastWarning: ReturnType<typeof vi.fn>;

// jsdom has no ResizeObserver; the button's collapse-on-overflow only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

/** Renders the page header's Import beside a list already loaded with these collections, for these actions. */
function renderImport(
    collections: GetCollectionRequest[],
    granted: ActionCode[] = [ActionCode.Read, ActionCode.Create, ActionCode.Update, ActionCode.Export]
): void {
    vi.stubGlobal('ResizeObserver', ResizeObserverStub);
    dialogOpen = vi.fn(() => ({ closed: EMPTY }));
    toastError = vi.fn();
    toastWarning = vi.fn();
    const can = (resource: ResourceCode, action: ActionCode): boolean =>
        resource === ResourceCode.KnowledgeSources && granted.includes(action);

    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
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
            { provide: ToastService, useValue: { error: toastError, warning: toastWarning, success: vi.fn() } },
        ],
    });
    httpMock = TestBed.inject(HttpTestingController);
    TestBed.inject(CollectionsStorageService).setCollections(collections);

    fixture = TestBed.createComponent(CollectionsImportComponent);
    fixture.detectChanges();
}

function host(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
}

function buttonLabelled(label: string): HTMLButtonElement | undefined {
    return [...host().querySelectorAll('button')].find((button) => button.textContent?.trim() === label);
}

function click(label: string): void {
    const button = buttonLabelled(label);
    expect(button, `a "${label}" button`).toBeDefined();
    button!.click();
    fixture.detectChanges();
}

function storedCollectionNames(): string[] {
    return TestBed.inject(CollectionsStorageService)
        .collections()
        .map((stored) => stored.collection_name);
}

afterEach(() => {
    httpMock.verify();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

describe('CollectionsImportComponent permissions', () => {
    it.each([
        { granted: [ActionCode.Read, ActionCode.Create], offered: true },
        { granted: [ActionCode.Read, ActionCode.Update, ActionCode.Export], offered: false },
    ])('offers Import only with the create permission ($granted)', ({ granted, offered }) => {
        renderImport([MANUALS], granted);

        expect(buttonLabelled('Import') !== undefined).toBe(offered);
    });
});

describe('CollectionsImportComponent', () => {
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
        renderImport([MANUALS]);

        await startArchiveImport();
        await finishImportJob(transferJob({ kind: 'import', status: 'completed', result: IMPORT_SUMMARY }));

        expect(dialogOpen).toHaveBeenCalledWith(
            ImportResultDialogComponent,
            expect.objectContaining({ data: { importResult: IMPORT_SUMMARY } })
        );
        httpMock.expectOne(COLLECTIONS_URL).flush([IMPORTED, MANUALS]);
        expect(storedCollectionNames()).toEqual(['Imported handbook', 'Manuals']);
        expect(toastError).not.toHaveBeenCalled();
    });

    it('says so, instead of showing an empty result, when the finished import reports no summary', async () => {
        renderImport([MANUALS]);

        await startArchiveImport();
        await finishImportJob(transferJob({ kind: 'import', status: 'completed', result: null }));

        expect(toastWarning).toHaveBeenCalledExactlyOnceWith(
            'The import has finished, but the server did not report what it brought in. Check the list for the new items.'
        );
        expect(dialogOpen).not.toHaveBeenCalled();
        httpMock.expectOne(COLLECTIONS_URL).flush([IMPORTED, MANUALS]);
    });

    it('stops waiting for the import job when the tab is left', async () => {
        vi.useFakeTimers();
        renderImport([MANUALS]);

        await startArchiveImport();
        const poll = await vi.waitFor(() => httpMock.expectOne(JOB_URL));
        fixture.destroy();

        expect(poll.cancelled).toBe(true);
        vi.advanceTimersByTime(TRANSFER_JOB_POLL_INTERVAL_MS * 3);
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
            return dialogOpen.mock.calls[0][1].data as ImportReviewDialogData;
        }

        function collect(source: Observable<unknown>): unknown[] {
            const values: unknown[] = [];
            source.subscribe((value) => values.push(value));
            return values;
        }

        it("imports the archive when the review dialog's Import is pressed and shows the result", async () => {
            renderImport([MANUALS]);
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
            renderImport([MANUALS]);
            await openReview(archiveToImport());

            reviewClosed.next({ action: 'cancel' });

            expect(dialogOpen).toHaveBeenCalledOnce();
            httpMock.expectNone((request) => request.url === IMPORT_JOBS_URL);
            httpMock.expectNone(COLLECTIONS_URL);
        });
    });

    describe('Import button while an import is on its way', () => {
        const FREE = { label: 'Import', ariaDisabled: null };
        const BUSY = { label: 'Importing…', ariaDisabled: 'true' };

        function importButton(): HTMLButtonElement {
            fixture.detectChanges();
            const button = [...host().querySelectorAll('button')].find((candidate) =>
                ['Import', 'Importing…'].includes(candidate.textContent!.trim())
            );
            expect(button, 'the Import button').toBeDefined();
            return button!;
        }

        function importButtonState(): { label: string; ariaDisabled: string | null } {
            const button = importButton();
            return { label: button.textContent!.trim(), ariaDisabled: button.getAttribute('aria-disabled') };
        }

        function acceptUpload(jobId: string): void {
            httpMock
                .expectOne((request) => request.url === IMPORT_JOBS_URL)
                .flush({ job_id: jobId }, { status: 202, statusText: 'Accepted' });
        }

        it("is busy from the file pick until the server has accepted the archive's import", async () => {
            renderImport([MANUALS]);

            const inspect = await chooseArchiveAndInspect(archiveToImport());
            expect(importButtonState()).toEqual(BUSY);
            const openedPickers = vi.spyOn(HTMLInputElement.prototype, 'click');
            importButton().click();
            expect(openedPickers).not.toHaveBeenCalled();

            inspect.flush({ review_items: [] });
            expect(importButtonState()).toEqual(BUSY);
            acceptUpload('job-1');
            expect(importButtonState()).toEqual(FREE);

            await finishImportJob(transferJob({ kind: 'import', status: 'completed', result: IMPORT_SUMMARY }));
            httpMock.expectOne(COLLECTIONS_URL).flush([IMPORTED, MANUALS]);
        });

        it.each([
            {
                step: 'the inspection',
                fail: (inspect: TestRequest) => inspect.flush({}, { status: 400, statusText: 'Bad' }),
            },
            {
                step: 'the upload',
                fail: (inspect: TestRequest) => {
                    inspect.flush({ review_items: [] });
                    httpMock
                        .expectOne((request) => request.url === IMPORT_JOBS_URL)
                        .flush(
                            {
                                type: 'client_error',
                                errors: [{ code: 'unknown', detail: 'Busy.', attr: null, context: null }],
                            },
                            { status: 429, statusText: 'Too Many Requests' }
                        );
                },
            },
        ])('is free again when $step fails', async ({ fail }) => {
            renderImport([MANUALS]);

            fail(await chooseArchiveAndInspect(archiveToImport()));

            expect(importButtonState()).toEqual(FREE);
            expect(toastError).toHaveBeenCalledOnce();
        });

        it('is free once the review dialog, with its own progress, opens, and stays free after a cancel', async () => {
            renderImport([MANUALS]);
            const reviewClosed = new Subject<ImportReviewDialogCloseResult>();
            dialogOpen.mockReturnValueOnce({ closed: reviewClosed });

            (await chooseArchiveAndInspect(archiveToImport())).flush({ review_items: [CODE_TO_REVIEW] });
            expect(importButtonState()).toEqual(FREE);

            reviewClosed.next({ action: 'cancel' });
            expect(importButtonState()).toEqual(FREE);
        });

        it("stays busy for a second import when the first one's job ends meanwhile", async () => {
            renderImport([MANUALS]);
            (await chooseArchiveAndInspect(archiveToImport())).flush({ review_items: [] });
            acceptUpload('job-1');

            const secondInspect = await chooseArchiveAndInspect(archiveToImport());
            await finishImportJob(transferJob({ kind: 'import', status: 'completed', result: IMPORT_SUMMARY }));
            httpMock.expectOne(COLLECTIONS_URL).flush([IMPORTED, MANUALS]);
            expect(importButtonState()).toEqual(BUSY);

            secondInspect.flush({ review_items: [] });
            acceptUpload('job-2');
            expect(importButtonState()).toEqual(FREE);
            (await vi.waitFor(() => httpMock.expectOne('/api/transfer-jobs/job-2/'))).flush(
                transferJob({ id: 'job-2', kind: 'import', status: 'completed', result: IMPORT_SUMMARY })
            );
            httpMock.expectOne(COLLECTIONS_URL).flush([IMPORTED, MANUALS]);
        });
    });

    it("reports a failed import job with the server's reason and leaves the list as it was", async () => {
        renderImport([MANUALS]);

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
        renderImport([MANUALS]);

        chooseFileToImport(new File([JSON.stringify({ main_entity: 'SourceCollection' })], 'collections.json'));

        await vi.waitFor(() =>
            expect(toastError).toHaveBeenCalledExactlyOnceWith(
                'Knowledge sources are imported from a .zip export. Choose a .zip file.'
            )
        );
        httpMock.expectNone(INSPECT_URL);
    });
});
