import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ConfirmationDialogService } from '@shared/components';
import { of } from 'rxjs';

import { ImportExportService } from '../../../../../../core/services/import-export.service';
import { ToastService } from '../../../../../../services/notifications';
import { FlowRenameDialogComponent } from '../../../../components/flow-rename-dialog/flow-rename-dialog.component';
import { GetGraphLightRequest } from '../../../../models/graph.model';
import { FlowsApiService } from '../../../../services/flows-api.service';
import { FlowsStorageService } from '../../../../services/flows-storage.service';
import { LabelsStorageService } from '../../../../services/labels-storage.service';
import { RunGraphService } from '../../../../services/run-graph-session.service';
import { MyFlowsComponent } from './my-flows.component';

const SOURCE_FLOW: GetGraphLightRequest = { id: 7, uuid: 'uuid-7', name: 'Support Flow', description: '' };

describe('MyFlowsComponent copy action', () => {
    const copyFlow = vi.fn();
    const toastSuccess = vi.fn();

    beforeEach(() => {
        copyFlow.mockReset().mockReturnValue(of({ name: 'Support Flow #2' }));
        toastSuccess.mockReset();

        TestBed.configureTestingModule({
            providers: [
                provideRouter([]),
                {
                    provide: FlowsStorageService,
                    useValue: {
                        filteredFlows: signal([]),
                        // Keeps the template on the spinner so no flow cards render.
                        isFlowsLoaded: signal(false),
                        selectMode: signal(false),
                        selectedFlowIds: signal([]),
                        getFlows: () => of([]),
                        copyFlow,
                    },
                },
                { provide: LabelsStorageService, useValue: { activeLabelFilter: signal('all') } },
                { provide: FlowsApiService, useValue: {} },
                { provide: RunGraphService, useValue: {} },
                { provide: ToastService, useValue: { success: toastSuccess, error: vi.fn() } },
                { provide: ConfirmationDialogService, useValue: {} },
                { provide: ImportExportService, useValue: {} },
            ],
        });
    });

    function openCopyDialog(closedWith: string | undefined): ReturnType<typeof vi.spyOn> {
        const fixture = TestBed.createComponent(MyFlowsComponent);
        fixture.detectChanges();
        // Spy on the Dialog instance the component actually injected (DialogModule provides its own).
        const dialog = fixture.debugElement.injector.get(Dialog);
        const openSpy = vi
            .spyOn(dialog, 'open')
            .mockReturnValue({ closed: of(closedWith) } as unknown as DialogRef<unknown, unknown>);

        fixture.componentInstance.handleFlowCardAction({ action: 'copy', flow: SOURCE_FLOW });
        return openSpy;
    }

    it('pre-fills the dialog with the plain source name, leaving numbering to the backend', () => {
        const openSpy = openCopyDialog(undefined);

        expect(openSpy).toHaveBeenCalledWith(
            FlowRenameDialogComponent,
            expect.objectContaining({ data: { flowName: 'Support Flow', title: 'Copy Flow' } })
        );
        expect(copyFlow).not.toHaveBeenCalled();
    });

    it('sends the name as entered, trimmed, without adding a number', () => {
        openCopyDialog('  Support Flow  ');

        expect(copyFlow).toHaveBeenCalledWith(7, 'Support Flow');
        expect(toastSuccess).toHaveBeenCalledWith('Flow copied and saved as "Support Flow #2"');
    });
});
