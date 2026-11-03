import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { CUSTOM_ELEMENTS_SCHEMA, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ConfirmationDialogService, LabelSidebarComponent, SearchComponent } from '@shared/components';
import { EXPORT_WARNING_DURATION_MS } from '@shared/constants';
import { ExcludedExportEntity } from '@shared/models';
import { AppStorageService } from '@shared/services';
import { EMPTY, Observable, of } from 'rxjs';

import { ImportResult } from '../../../../core/models/import-result.model';
import { ImportReviewDialogData, ReviewItem } from '../../../../core/models/review-item.model';
import { ImportExportService } from '../../../../core/services/import-export.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { RecycleBinSettingsService } from '../../../../services/recycle-bin';
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

// jsdom has no ResizeObserver; the overflow directives in the header only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('FlowsListPageComponent flow import', () => {
    let dialogOpen: ReturnType<typeof vi.fn>;
    let confirm: ReturnType<typeof vi.fn>;
    let toastError: ReturnType<typeof vi.fn>;
    let httpMock: HttpTestingController;
    let fixture: ComponentFixture<FlowsListPageComponent>;
    let file: File;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        dialogOpen = vi.fn(() => ({ closed: EMPTY }));
        confirm = vi.fn();
        toastError = vi.fn();
        file = new File(['{}'], 'flow.json');

        TestBed.configureTestingModule({
            providers: [
                provideRouter([]),
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                { provide: PermissionsService, useValue: { can: () => true, canAny: () => true } },
                { provide: Dialog, useValue: { open: dialogOpen } },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: ToastService, useValue: { error: toastError, success: vi.fn() } },
                { provide: AppStorageService, useValue: { invalidate: vi.fn() } },
                { provide: RecycleBinSettingsService, useValue: { retentionDays: signal(7) } },
                {
                    provide: FlowsStorageService,
                    useValue: {
                        selectMode: signal(false),
                        selectedFlowIds: signal([]),
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
    const toastWarning = vi.fn();
    const setSelectMode = vi.fn();

    function confirmExportWith(excluded: ExcludedExportEntity[]): void {
        toastWarning.mockReset();
        setSelectMode.mockReset();
        window.URL.createObjectURL = vi.fn(() => 'blob:x');
        window.URL.revokeObjectURL = vi.fn();
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);

        TestBed.configureTestingModule({
            providers: [
                provideRouter([]),
                provideHttpClient(),
                provideHttpClientTesting(),
                {
                    provide: FlowsStorageService,
                    useValue: { selectedFlowIds: signal([1, 2]), setSelectMode, resetFilter: vi.fn() },
                },
                { provide: LabelsStorageService, useValue: {} },
                { provide: ToastService, useValue: { warning: toastWarning, error: vi.fn() } },
                {
                    provide: ImportExportService,
                    useValue: { bulkExportFlow: () => of({ blob: new Blob(['{}']), excluded }) },
                },
            ],
        });
        // The template is irrelevant to the export flow, so it is replaced with an empty one.
        TestBed.overrideComponent(FlowsListPageComponent, {
            set: { template: '', templateUrl: undefined, styleUrls: [], imports: [] },
        });
        const fixture = TestBed.createComponent(FlowsListPageComponent);
        fixture.componentInstance.confirmExport();
    }

    afterEach(() => vi.restoreAllMocks());

    it('warns, with a long duration, about entities left out of the export', () => {
        confirmExportWith([{ type: 'Flow', count: 1, names: [] }]);

        expect(setSelectMode).toHaveBeenCalledWith(false);
        expect(toastWarning).toHaveBeenCalledWith(
            expect.stringContaining('1 subflow'),
            EXPORT_WARNING_DURATION_MS,
            undefined
        );
    });

    it('shows no warning when nothing was excluded', () => {
        confirmExportWith([]);

        expect(setSelectMode).toHaveBeenCalledWith(false);
        expect(toastWarning).not.toHaveBeenCalled();
    });
});
