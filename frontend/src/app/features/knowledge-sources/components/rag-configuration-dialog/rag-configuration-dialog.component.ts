import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, DestroyRef, inject } from '@angular/core';
import { ConfirmationDialogService } from '@shared/components';

import { ToastService } from '../../../../services/notifications';

@Component({
    template: '',
})
export abstract class RagConfigurationDialogComponent {
    protected data: { ragId: number; collectionId: number } = inject(DIALOG_DATA);
    protected destroyRef = inject(DestroyRef);
    protected dialogRef = inject(DialogRef);
    protected toast = inject(ToastService);
    protected confirmation = inject(ConfirmationDialogService);

    protected abstract onClose(): void;
    protected abstract runIndexing(): void;
}
