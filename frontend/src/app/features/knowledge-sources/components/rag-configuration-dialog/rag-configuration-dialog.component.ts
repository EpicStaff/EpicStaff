import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, DestroyRef, inject } from '@angular/core';

import { ToastService } from '../../../../services/notifications';

@Component({
    template: '',
})
export abstract class RagConfigurationDialogComponent {
    protected data: { ragId: number } = inject(DIALOG_DATA);
    protected destroyRef = inject(DestroyRef);
    protected dialogRef = inject(DialogRef);
    protected toast = inject(ToastService);

    protected abstract onClose(): void;
    protected abstract runIndexing(): void;
}
