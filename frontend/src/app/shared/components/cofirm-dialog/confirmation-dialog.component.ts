import { DIALOG_DATA, DialogModule, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';

import { AppIconComponent } from '../app-icon/app-icon.component';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { IconButtonComponent } from '../buttons/icon-button/icon-button.component';

export type DialogResult = 'confirm' | 'cancel' | 'close';

let nextBreakdownListId = 0;

export interface ConfirmationBreakdownItem {
    label: string;
    count: number;
}

export interface ConfirmationBreakdown {
    title: string;
    items: ConfirmationBreakdownItem[];
}

export interface ConfirmationDialogData {
    title: string;
    message: string;
    confirmText?: string;
    cancelText?: string;
    type?: 'warning' | 'danger' | 'info';
    caution?: string;
    cautionTitle?: string;
    isShownBorder?: boolean;
    /** Hide the confirm button entirely -- for informational dialogs the caller
     *  cannot actually proceed with (e.g. blocked by a missing permission).
     *  The cancel button then acts as a plain close. */
    hideConfirm?: boolean;
    /** Collapsible list of counted items shown under the message, with their total in the header. */
    breakdown?: ConfirmationBreakdown;
}

@Component({
    selector: 'app-confirmation-dialog',
    imports: [CommonModule, DialogModule, IconButtonComponent, AppSvgIconComponent, AppIconComponent],
    templateUrl: './confirmation-dialog.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrls: ['./confirmation-dialog.component.scss'],
})
export class ConfirmationDialogComponent {
    protected readonly isBreakdownExpanded = signal(false);

    // `data` must stay above the fields below: they read it in their initializers.
    readonly data = inject<ConfirmationDialogData>(DIALOG_DATA);
    protected readonly breakdownListId = `confirmation-breakdown-list-${nextBreakdownListId++}`;
    protected readonly breakdown = this.data.breakdown?.items.length ? this.data.breakdown : null;
    protected readonly breakdownTotal = (this.breakdown?.items ?? []).reduce((sum, item) => sum + item.count, 0);

    private readonly dialogRef = inject<DialogRef<DialogResult>>(DialogRef);

    toggleBreakdown(): void {
        this.isBreakdownExpanded.update((isExpanded) => !isExpanded);
    }

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
