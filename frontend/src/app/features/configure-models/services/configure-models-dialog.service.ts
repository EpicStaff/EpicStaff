import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { inject, Injectable } from '@angular/core';

import { ConfigureModelsDialogComponent } from '../components/configure-models-dialog/configure-models-dialog.component';

export const SETTINGS_DIALOG_SIZE = {
    width: 'calc(100vw - 2rem)',
    height: 'calc(100vh - 2rem)',
} as const;

@Injectable({
    providedIn: 'root',
})
export class ConfigureModelsDialogService {
    private readonly dialog: Dialog = inject(Dialog);
    private openDialogRef: DialogRef<void> | null = null;

    /**
     * Opens the Settings dialog, or returns the already open one — there is only ever one. The Quick Start tour
     * relies on this: clicking the Settings icon during the tour runs both the sidenav handler and the tour's own.
     */
    public open(): DialogRef<void> {
        if (this.openDialogRef) {
            return this.openDialogRef;
        }

        const dialogRef = this.dialog.open<void>(ConfigureModelsDialogComponent, SETTINGS_DIALOG_SIZE);
        this.openDialogRef = dialogRef;
        dialogRef.closed.subscribe(() => (this.openDialogRef = null));
        return dialogRef;
    }

    public close(): void {
        this.openDialogRef?.close();
    }
}
