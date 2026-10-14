import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { EMPTY } from 'rxjs';

import { ImportReviewDialogData } from '../../../../core/models/review-item.model';
import { ToastService } from '../../../../services/notifications';
import { ImportReviewDialogComponent } from './import-review-dialog.component';

describe('ImportReviewDialogComponent', () => {
    it('stays open and usable when the import ends without a result (a refusal already explained)', () => {
        const dialogRef = { close: vi.fn(), disableClose: false };
        const toastError = vi.fn();
        const data: ImportReviewDialogData = {
            importResult: {},
            reviewItems: [],
            allFlowNodes: {},
            importFn: () => EMPTY,
        };
        TestBed.configureTestingModule({
            providers: [
                { provide: DialogRef, useValue: dialogRef },
                { provide: DIALOG_DATA, useValue: data },
                { provide: ToastService, useValue: { error: toastError } },
                { provide: ConfirmationDialogService, useValue: { confirm: vi.fn() } },
            ],
        });
        TestBed.overrideComponent(ImportReviewDialogComponent, { set: { template: '', imports: [] } });
        const component = TestBed.createComponent(ImportReviewDialogComponent).componentInstance;

        component.onImport();

        expect(dialogRef.close).not.toHaveBeenCalled();
        expect(component.isImporting()).toBe(false);
        expect(dialogRef.disableClose).toBe(false);
        expect(toastError).not.toHaveBeenCalled();
    });
});
