import { Dialog } from '@angular/cdk/dialog';
import { inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { escapeHtml } from '../../utils/escape-html.util';
import { recycleBinNotice } from '../../utils/recycle-bin-notice.util';
import { ConfirmationDialogComponent, ConfirmationDialogData, DialogResult } from './confirmation-dialog.component';

export type ConfirmationResult = boolean | 'close';

export interface ConfirmationResultWithOptions {
    confirmed: boolean;
    checked: boolean;
}

interface ConfirmationDialogConfig {
    width?: string;
    panelClass?: string;
}

@Injectable({
    providedIn: 'root',
})
export class ConfirmationDialogService {
    private readonly dialog = inject(Dialog);

    confirm(options: ConfirmationDialogData, config?: ConfirmationDialogConfig): Observable<ConfirmationResult> {
        return this.openDialog(options, config).pipe(
            map((result) => {
                if (!result) return 'close';
                if (result.action === 'confirm') return true;
                if (result.action === 'cancel') return false;
                return 'close';
            })
        );
    }

    confirmWithOptions(
        options: ConfirmationDialogData,
        config?: ConfirmationDialogConfig
    ): Observable<ConfirmationResultWithOptions | 'close'> {
        return this.openDialog(options, config).pipe(
            map((result) => {
                if (!result || result.action === 'close') return 'close';
                return {
                    confirmed: result.action === 'confirm',
                    checked: result.checked ?? false,
                };
            })
        );
    }

    private openDialog(
        options: ConfirmationDialogData,
        config?: ConfirmationDialogConfig
    ): Observable<DialogResult | undefined> {
        const dialogRef = this.dialog.open<DialogResult>(ConfirmationDialogComponent, {
            width: config?.width ?? '400px',
            panelClass: config?.panelClass,
            data: options,
        });
        return dialogRef.closed;
    }

    confirmDelete(itemName: string): Observable<ConfirmationResult> {
        return this.confirm({
            title: 'Confirm Deletion',
            message: `Are you sure you want to delete <strong>${escapeHtml(itemName)}</strong>? <br> This action cannot be undone.`,
            confirmText: 'Delete',
            cancelText: 'Cancel',
            type: 'danger',
        });
    }

    /** Delete confirmation for an item that moves to the recycle bin. Truncates, then escapes, the name. */
    confirmMoveToRecycleBin(
        itemName: string,
        retentionDays: number | null,
        maxLength: number = 50
    ): Observable<ConfirmationResult> {
        // Truncate first: escaping first could cut an entity like &amp; in half.
        const truncatedName = itemName.length > maxLength ? `${itemName.substring(0, maxLength)}...` : itemName;

        return this.confirm({
            title: 'Confirm Deletion',
            message: `Are you sure you want to delete <strong>${escapeHtml(truncatedName)}</strong>? ${recycleBinNotice(retentionDays)}`,
            confirmText: 'Delete',
            cancelText: 'Cancel',
            type: 'danger',
        });
    }
}
