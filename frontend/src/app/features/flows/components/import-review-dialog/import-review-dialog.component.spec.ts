import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Subject } from 'rxjs';

import { ImportResult } from '../../../../core/models/import-result.model';
import { ImportReviewDialogData } from '../../../../core/models/review-item.model';
import { ToastService } from '../../../../services/notifications';
import { ImportReviewDialogComponent } from './import-review-dialog.component';

// jsdom has no ResizeObserver; the overflow directive behind <app-button> only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('ImportReviewDialogComponent', () => {
    let importResponse$: Subject<ImportResult>;
    let dialogRef: { close: ReturnType<typeof vi.fn>; disableClose: boolean; keydownEvents: Subject<KeyboardEvent> };
    let toastError: ReturnType<typeof vi.fn>;
    let fixture: ComponentFixture<ImportReviewDialogComponent>;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        importResponse$ = new Subject<ImportResult>();
        dialogRef = { close: vi.fn(), disableClose: false, keydownEvents: new Subject<KeyboardEvent>() };
        toastError = vi.fn();
        const data: ImportReviewDialogData = {
            importResult: {},
            // Nothing to review, so Import imports at once.
            reviewItems: [],
            allFlowNodes: {},
            importFn: () => importResponse$,
        };
        TestBed.configureTestingModule({
            providers: [
                { provide: DialogRef, useValue: dialogRef },
                { provide: DIALOG_DATA, useValue: data },
                { provide: ToastService, useValue: { error: toastError } },
                { provide: ConfirmationDialogService, useValue: { confirm: vi.fn() } },
            ],
        });
        fixture = TestBed.createComponent(ImportReviewDialogComponent);
        fixture.detectChanges();
    });

    afterEach(() => vi.unstubAllGlobals());

    function importButton(): HTMLButtonElement {
        const buttons = Array.from(
            (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('.dialog-header-actions button')
        );
        return buttons.find((button) => /Import/.test(button.textContent ?? ''))!;
    }

    it('stays open and usable when the import ends without a result (a refusal already explained)', () => {
        importButton().click();
        fixture.detectChanges();
        expect(importButton().textContent?.trim()).toBe('Importing…');
        expect(importButton().disabled).toBe(true);
        expect(dialogRef.disableClose).toBe(true);

        importResponse$.complete();
        fixture.detectChanges();

        expect(dialogRef.close).not.toHaveBeenCalled();
        expect(importButton().textContent?.trim()).toBe('Import');
        expect(importButton().disabled).toBe(false);
        expect(dialogRef.disableClose).toBe(false);
        expect(toastError).not.toHaveBeenCalled();
    });
});
