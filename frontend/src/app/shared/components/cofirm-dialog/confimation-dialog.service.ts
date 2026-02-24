import { Injectable } from '@angular/core';
import { Dialog } from '@angular/cdk/dialog';
import { Observable, map } from 'rxjs';
import {
  ConfirmationDialogData,
  ConfirmationDialogComponent,
  DialogResult,
} from './confirmation-dialog.component';

export type ConfirmationResult = boolean | 'close';

@Injectable({
  providedIn: 'root',
})
export class ConfirmationDialogService {
  constructor(private dialog: Dialog) {}

  confirm(options: ConfirmationDialogData): Observable<ConfirmationResult> {
    const dialogRef = this.dialog.open<DialogResult>(
      ConfirmationDialogComponent,
      {
        width: '400px',
        data: options,
      }
    );

    return dialogRef.closed.pipe(
      map((result) => {
        if (!result) return 'close';
        if (result === 'confirm') return true;
        if (result === 'cancel') return false;
        return 'close';
      })
    );
  }

  confirmDelete(itemName: string): Observable<ConfirmationResult> {
    return this.confirm({
      title: 'Confirm Deletion',
      message: `Are you sure you want to delete <strong>${itemName}</strong>? <br> This action cannot be undone.`,
      confirmText: 'Delete',
      cancelText: 'Cancel',
      type: 'danger',
    });
  }

  confirmDeleteWithTruncation(
    itemName: string,
    maxLength: number = 50
  ): Observable<ConfirmationResult> {
    const truncatedName =
      itemName.length > maxLength
        ? `${itemName.substring(0, maxLength)}...`
        : itemName;

    return this.confirm({
      title: 'Confirm Deletion',
      message: `Are you sure you want to delete <strong>${truncatedName}</strong>? <br> This action cannot be undone.`,
      confirmText: 'Delete',
      cancelText: 'Cancel',
      type: 'danger',
    });
  }
}
