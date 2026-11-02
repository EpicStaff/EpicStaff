import { Dialog } from '@angular/cdk/dialog';
import { inject, Injectable } from '@angular/core';
import { ConfirmationResult } from '@shared/components';
import { map, Observable } from 'rxjs';

import {
    INDEXING_CONFIRMATION_DIALOG_TITLE_ID,
    IndexingConfirmationDialogComponent,
    IndexingConfirmationDialogData,
} from '../components/indexing-confirmation-dialog/indexing-confirmation-dialog.component';

const DIALOG_WIDTH = '480px';

/** Opens the "Confirm Indexing" dialog; answers like `ConfirmationDialogService.confirm`. */
@Injectable({
    providedIn: 'root',
})
export class IndexingConfirmationDialogService {
    private readonly dialog = inject(Dialog);

    /** `true` to start indexing, `false` on Cancel, `'close'` on the close button, Escape or a click outside. */
    confirm(data: IndexingConfirmationDialogData): Observable<ConfirmationResult> {
        return this.dialog
            .open<ConfirmationResult, IndexingConfirmationDialogData>(IndexingConfirmationDialogComponent, {
                width: DIALOG_WIDTH,
                maxWidth: 'calc(100vw - 2rem)',
                data,
                ariaLabelledBy: INDEXING_CONFIRMATION_DIALOG_TITLE_ID,
            })
            .closed.pipe(map((result) => result ?? 'close'));
    }
}
