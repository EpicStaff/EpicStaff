import { DIALOG_DATA, DialogModule, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { Component, Inject } from '@angular/core';
import { Observable, of } from 'rxjs';
import { catchError, finalize } from 'rxjs/operators';

import { IconButtonComponent } from '../buttons/icon-button/icon-button.component';

export type UnsavedChangesDialogResult = 'save' | 'dont-save' | 'cancel' | 'close';

export interface UnsavedChangesDialogData {
    title: string;
    message: string;
    saveText?: string;
    dontSaveText?: string;
    cancelText?: string;
    type?: 'warning' | 'danger' | 'info';
    onSave?: () => Observable<boolean>;
}

@Component({
    selector: 'app-unsaved-changes-dialog',
    standalone: true,
    imports: [CommonModule, DialogModule, IconButtonComponent],
    templateUrl: './unsaved-changes-dialog.component.html',
    styleUrls: ['./unsaved-changes-dialog.component.scss'],
})
export class UnsavedChangesDialogComponent {
    public isSaving = false;

    constructor(
        public dialogRef: DialogRef<UnsavedChangesDialogResult>,
        @Inject(DIALOG_DATA) public data: UnsavedChangesDialogData
    ) {}

    onCancel(): void {
        this.dialogRef.close('cancel');
    }

    onDontSave(): void {
        this.dialogRef.close('dont-save');
    }

    onSave(): void {
        this.isSaving = true;

        if (this.data.onSave) {
            this.data
                .onSave()
                .pipe(
                    catchError(() => of(false)),
                    finalize(() => {
                        this.isSaving = false;
                    })
                )
                .subscribe((success) => {
                    if (success) {
                        this.dialogRef.close('save');
                    }
                });
        } else {
            this.dialogRef.close('save');
        }
    }

    onClose(): void {
        this.dialogRef.close('close');
    }
}
