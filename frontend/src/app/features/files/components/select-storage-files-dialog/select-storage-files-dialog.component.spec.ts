import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { of, throwError } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { StorageApiService } from '../../services/storage-api.service';
import { StorageUploadService } from '../../services/storage-upload.service';
import { SelectStorageFilesDialogComponent } from './select-storage-files-dialog.component';

describe('SelectStorageFilesDialogComponent saving', () => {
    let addToGraph: ReturnType<typeof vi.fn>;
    let toast: { success: ReturnType<typeof vi.fn>; error: ReturnType<typeof vi.fn> };
    let close: ReturnType<typeof vi.fn>;

    function saveAddingFile(addRequest: unknown): void {
        addToGraph.mockReturnValue(addRequest);
        const fixture = TestBed.createComponent(SelectStorageFilesDialogComponent);
        fixture.componentInstance.selectedFilePaths.set(new Set(['notes.txt']));
        fixture.componentInstance.onConfirm();
    }

    beforeEach(() => {
        addToGraph = vi.fn();
        toast = { success: vi.fn(), error: vi.fn() };
        close = vi.fn();
        TestBed.configureTestingModule({
            providers: [
                { provide: DialogRef, useValue: { close, keydownEvents: of(), backdropClick: of() } },
                { provide: DIALOG_DATA, useValue: { flowId: 5, flowName: 'Flow' } },
                {
                    provide: StorageApiService,
                    useValue: {
                        addToGraph,
                        removeFromGraph: vi.fn(),
                        getUploadLimits: () => throwError(() => new Error('none')),
                    },
                },
                { provide: StorageUploadService, useValue: {} },
                { provide: ConfirmationDialogService, useValue: {} },
                { provide: ToastService, useValue: toast },
                { provide: PermissionsService, useValue: { can: () => true } },
            ],
        });
    });

    it('shows the server message when adding files is refused for missing Files permissions', () => {
        const message = "This file is used by code that runs with Files: Write, which you don't have.";
        saveAddingFile(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 403,
                        error: { status_code: 403, code: 'storage_grant_denied', message, missing_grants: ['write'] },
                    })
            )
        );

        expect(toast.error).toHaveBeenCalledExactlyOnceWith(message);
        expect(close).not.toHaveBeenCalled();
    });

    it('keeps the generic text for a server failure', () => {
        saveAddingFile(throwError(() => new HttpErrorResponse({ status: 500, error: { message: 'boom' } })));

        expect(toast.error).toHaveBeenCalledExactlyOnceWith('Failed to update files');
    });
});
