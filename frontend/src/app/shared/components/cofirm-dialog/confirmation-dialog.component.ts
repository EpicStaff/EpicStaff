import { DIALOG_DATA, DialogModule, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { Component, Inject } from '@angular/core';

import { IconButtonComponent } from '../buttons/icon-button/icon-button.component';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

export type DialogResult = 'confirm' | 'cancel' | 'close';

export interface ConfirmationDialogData {
    title: string;
    message: string;
    confirmText?: string;
    cancelText?: string;
    type?: 'warning' | 'danger' | 'info';
    caution?: string;
    isShownBorder?: boolean;
}

@Component({
    selector: 'app-confirmation-dialog',
    standalone: true,
    imports: [CommonModule, DialogModule, IconButtonComponent, AppSvgIconComponent],
    templateUrl: './confirmation-dialog.component.html',
    styleUrls: ['./confirmation-dialog.component.scss'],
})
export class ConfirmationDialogComponent {
    constructor(
        public dialogRef: DialogRef<DialogResult>,
        @Inject(DIALOG_DATA) public data: ConfirmationDialogData
    ) {}

    onCancel(): void {
        this.dialogRef.close('cancel');
    }

    onConfirm(): void {
        this.dialogRef.close('confirm');
    }

    onClose(): void {
        this.dialogRef.close('close');
    }
}
