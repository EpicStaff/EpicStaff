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
    ValidationErrorsComponent,
} from '@shared/components';
import { extractHttpErrorMessage } from '@shared/utils';
import { Observable } from 'rxjs';

import { KeyValueTable } from '../../models/key-value-table.model';
import { KeyValueTablesApiService } from '../../services/key-value-tables-api.service';

export interface KeyValueTableDialogData {
    table?: KeyValueTable;
}

@Component({
    selector: 'app-key-value-table-dialog',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        ValidationErrorsComponent,
        ButtonComponent,
        AppSvgIconComponent,
        MatTooltipModule,
    ],
    templateUrl: './key-value-table-dialog.component.html',
    styleUrls: ['./key-value-table-dialog.component.scss'],
})
export class KeyValueTableDialogComponent {
    readonly isSubmitting = signal(false);
    readonly errorMessage = signal<string | null>(null);

    readonly data = inject<KeyValueTableDialogData | null>(DIALOG_DATA, { optional: true }) ?? {};
    readonly isRename = !!this.data.table;
    readonly form = new FormGroup({
        name: new FormControl(this.data.table?.name ?? '', {
            nonNullable: true,
            validators: [Validators.required, Validators.maxLength(255)],
        }),
        description: new FormControl(this.data.table?.description ?? '', { nonNullable: true }),
    });

    private readonly dialogRef = inject<DialogRef<KeyValueTable | null>>(DialogRef);
    private readonly keyValueTablesApi = inject(KeyValueTablesApiService);
    private readonly destroyRef = inject(DestroyRef);

    submit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }
        if (this.isSubmitting()) return;

        this.isSubmitting.set(true);
        this.errorMessage.set(null);
        const body = this.form.getRawValue();
        const request$: Observable<KeyValueTable> = this.data.table
            ? this.keyValueTablesApi.updateTable(this.data.table.id, body)
            : this.keyValueTablesApi.createTable(body);

        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (table) => this.dialogRef.close(table),
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
