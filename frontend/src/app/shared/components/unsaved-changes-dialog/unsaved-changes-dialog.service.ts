import { Dialog } from '@angular/cdk/dialog';
import { Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import {
    UnsavedChangesDialogComponent,
    UnsavedChangesDialogData,
    UnsavedChangesDialogResult,
} from './unsaved-changes-dialog.component';

export type UnsavedChangesResult = 'save' | 'dont-save' | 'cancel' | 'close';

@Injectable({
    providedIn: 'root',
})
export class UnsavedChangesDialogService {
    constructor(private dialog: Dialog) {}

    confirm(options: UnsavedChangesDialogData): Observable<UnsavedChangesResult> {
        const dialogRef = this.dialog.open<UnsavedChangesDialogResult>(UnsavedChangesDialogComponent, {
            width: '400px',
            data: options,
        });

        return dialogRef.closed.pipe(
            map((result) => {
                if (!result) return 'close';
                return result;
            })
        );
    }

    confirmUnsavedChanges(onSave?: () => Observable<boolean>): Observable<UnsavedChangesResult> {
        return this.confirm({
            title: 'Unsaved Changes',
            message: 'You have unsaved changes in your flow. What would you like to do?',
            saveText: 'Save & Leave',
            dontSaveText: "Don't Save & Leave",
            cancelText: 'Cancel',
            type: 'warning',
            onSave,
        });
    }
}
