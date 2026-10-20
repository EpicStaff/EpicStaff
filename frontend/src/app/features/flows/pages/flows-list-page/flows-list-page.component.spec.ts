import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { EXPORT_WARNING_DURATION_MS } from '@shared/constants';
import { ExcludedExportEntity } from '@shared/models';
import { of } from 'rxjs';

import { ImportExportService } from '../../../../core/services/import-export.service';
import { ToastService } from '../../../../services/notifications';
import { FlowsStorageService } from '../../services/flows-storage.service';
import { LabelsStorageService } from '../../services/labels-storage.service';
import { FlowsListPageComponent } from './flows-list-page.component';

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
