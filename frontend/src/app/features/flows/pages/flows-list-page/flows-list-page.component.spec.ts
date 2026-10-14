import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { AppStorageService } from '@shared/services';
import { EMPTY, Observable, of, throwError } from 'rxjs';

import { ImportResult } from '../../../../core/models/import-result.model';
import { ImportReviewDialogData, ReviewItem } from '../../../../core/models/review-item.model';
import { ImportExportService } from '../../../../core/services/import-export.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { ImportResultDialogComponent } from '../../components/import-result-dialog/import-result-dialog.component';
import { ImportReviewDialogComponent } from '../../components/import-review-dialog/import-review-dialog.component';
import { EMPTY_FLOWS_FILTER } from '../../models/flow-filter.model';
import { FlowCopyImportFacadeService } from '../../services/flow-copy-import-facade.service';
import { FlowsStorageService } from '../../services/flows-storage.service';
import { ImportFlowSettingsService } from '../../services/import-flow-settings.service';
import { LabelsStorageService } from '../../services/labels-storage.service';
import { FlowsListPageComponent } from './flows-list-page.component';

const SUMMARY: ImportResult = {
    Flow: { total: 1, created: { count: 1, items: [{ id: 3, name: 'Orders' }] }, reused: { count: 0, items: [] } },
};
const SETTINGS = { preserveUuids: false, replaceExisting: true, importLabels: true };
const CODE_TO_REVIEW: ReviewItem = { kind: 'mcp_tool', name: 'Search', transport: 'stdio' };

describe('FlowsListPageComponent flow import', () => {
    let importFlow: ReturnType<typeof vi.fn>;
    let inspectFlow: ReturnType<typeof vi.fn>;
    let dialogOpen: ReturnType<typeof vi.fn>;
    let toastError: ReturnType<typeof vi.fn>;
    let file: File;

    beforeEach(() => {
        importFlow = vi.fn();
        // No code to review by default, so the file is imported right away.
        inspectFlow = vi.fn(() => of({ review_items: [] }));
        dialogOpen = vi.fn(() => ({ closed: EMPTY }));
        toastError = vi.fn();
        file = new File(['{}'], 'flow.json');

        TestBed.configureTestingModule({
            providers: [
                provideRouter([]),
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                { provide: Dialog, useValue: { open: dialogOpen } },
                { provide: ImportExportService, useValue: { inspectFlow } },
                { provide: FlowCopyImportFacadeService, useValue: { importFlow } },
                { provide: ImportFlowSettingsService, useValue: { requestSettings: () => SETTINGS } },
                { provide: ToastService, useValue: { error: toastError, success: vi.fn() } },
                { provide: AppStorageService, useValue: { invalidate: vi.fn() } },
                {
                    provide: FlowsStorageService,
                    useValue: {
                        selectMode: signal(false),
                        selectedFlowIds: signal([]),
                        filter: signal(EMPTY_FLOWS_FILTER),
                        flows: signal([]),
                        getFlows: () => of([]),
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
                        loadLabels: () => of([]),
                    },
                },
            ],
        });
        // Only the import is under test; the page's children bring their own services.
        TestBed.overrideComponent(FlowsListPageComponent, { set: { template: '', imports: [] } });
    });

    async function importFile(response: Observable<ImportResult>): Promise<void> {
        importFlow.mockReturnValue(response);
        const component = TestBed.createComponent(FlowsListPageComponent).componentInstance;
        const input = document.createElement('input');
        vi.spyOn(input, 'click').mockImplementation(() => undefined);
        const createElement = vi.spyOn(document, 'createElement').mockReturnValueOnce(input);

        component.onImportClick();
        createElement.mockRestore();
        Object.defineProperty(input, 'files', { value: [file] });
        input.dispatchEvent(new Event('change'));
        // The file is read asynchronously before the import starts.
        await vi.waitFor(() => expect(inspectFlow).toHaveBeenCalled());
    }

    it('imports through the facade and shows the result', async () => {
        await importFile(of(SUMMARY));

        expect(importFlow).toHaveBeenCalledExactlyOnceWith(file, SETTINGS);
        expect(dialogOpen).toHaveBeenCalledWith(
            ImportResultDialogComponent,
            expect.objectContaining({ data: { importResult: SUMMARY } })
        );
    });

    it('stays silent when the facade has explained an import refused over trigger nodes', async () => {
        // The facade shows the refusal and completes without emitting.
        await importFile(EMPTY);

        expect(importFlow).toHaveBeenCalled();
        expect(dialogOpen).not.toHaveBeenCalled();
        expect(toastError).not.toHaveBeenCalled();
    });

    it('reports any other import failure', async () => {
        await importFile(throwError(() => new HttpErrorResponse({ status: 400, error: { message: 'Bad file' } })));

        expect(toastError).toHaveBeenCalled();
        expect(dialogOpen).not.toHaveBeenCalled();
    });

    it('imports from the code review dialog through the facade too', async () => {
        inspectFlow.mockReturnValue(of({ review_items: [CODE_TO_REVIEW] }));

        await importFile(of(SUMMARY));

        expect(dialogOpen).toHaveBeenCalledWith(ImportReviewDialogComponent, expect.anything());
        const reviewData = dialogOpen.mock.calls[0][1].data as ImportReviewDialogData;
        expect(importFlow).not.toHaveBeenCalled();
        reviewData.importFn().subscribe();
        expect(importFlow).toHaveBeenCalledExactlyOnceWith(file, SETTINGS);
    });
});
