import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CustomInputComponent,
    JsonEditorFormFieldComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { extractHttpErrorMessage } from '@shared/utils';
import { Observable } from 'rxjs';

import { PersistenceTableEntry } from '../../models/persistence-table.model';
import { PersistenceTablesApiService } from '../../services/persistence-tables-api.service';

export interface PersistenceEntryDialogData {
    tableId: number;
    entry?: PersistenceTableEntry;
}

@Component({
    selector: 'app-persistence-entry-dialog',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        ValidationErrorsComponent,
        JsonEditorFormFieldComponent,
        ButtonComponent,
        AppSvgIconComponent,
        MatTooltipModule,
    ],
    templateUrl: './persistence-entry-dialog.component.html',
    // Shares the dialog frame styles with the table dialog; the local file only widens it for the JSON editor.
    styleUrls: [
        '../persistence-table-dialog/persistence-table-dialog.component.scss',
        './persistence-entry-dialog.component.scss',
    ],
})
export class PersistenceEntryDialogComponent {
    readonly isSubmitting = signal(false);
    readonly errorMessage = signal<string | null>(null);

    readonly data = inject<PersistenceEntryDialogData>(DIALOG_DATA);
    readonly isEdit = !!this.data.entry;
    readonly form = new FormGroup({
        // Keys are the entry's identity, so they are fixed once the entry exists.
        key: new FormControl(
            { value: this.data.entry?.key ?? '', disabled: this.isEdit },
            { nonNullable: true, validators: [Validators.required, Validators.maxLength(512)] }
        ),
        // JSON text; parsed on submit.
        value: new FormControl(this.data.entry ? JSON.stringify(this.data.entry.value, null, 2) : 'null', {
            nonNullable: true,
        }),
    });

    private readonly dialogRef = inject<DialogRef<PersistenceTableEntry | null>>(DialogRef);
    private readonly persistenceTablesApi = inject(PersistenceTablesApiService);
    private readonly destroyRef = inject(DestroyRef);

    submit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }
        if (this.isSubmitting()) return;

        let value: unknown;
        try {
            value = JSON.parse(this.form.controls.value.value);
        } catch {
            this.errorMessage.set('Value must be valid JSON');
            return;
        }

        this.isSubmitting.set(true);
        this.errorMessage.set(null);
        const request$: Observable<PersistenceTableEntry> = this.data.entry
            ? this.persistenceTablesApi.updateEntry(this.data.entry.id, { value })
            : this.persistenceTablesApi.createEntry({
                  table: this.data.tableId,
                  key: this.form.controls.key.value,
                  value,
              });

        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (entry) => this.dialogRef.close(entry),
            error: (error: HttpErrorResponse) => {
                this.isSubmitting.set(false);
                this.errorMessage.set(extractHttpErrorMessage(error));
            },
        });
    }

    cancel(): void {
        this.dialogRef.close(null);
    }
}
