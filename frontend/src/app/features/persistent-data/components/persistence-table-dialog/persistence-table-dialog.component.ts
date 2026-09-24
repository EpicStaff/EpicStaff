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

import { PersistenceTable } from '../../models/persistence-table.model';
import { PersistenceTablesApiService } from '../../services/persistence-tables-api.service';

export interface PersistenceTableDialogData {
    table?: PersistenceTable;
}

@Component({
    selector: 'app-persistence-table-dialog',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        ValidationErrorsComponent,
        ButtonComponent,
        AppSvgIconComponent,
        MatTooltipModule,
    ],
    templateUrl: './persistence-table-dialog.component.html',
    styleUrls: ['./persistence-table-dialog.component.scss'],
})
export class PersistenceTableDialogComponent {
    readonly isSubmitting = signal(false);
    readonly errorMessage = signal<string | null>(null);

    readonly data = inject<PersistenceTableDialogData | null>(DIALOG_DATA, { optional: true }) ?? {};
    readonly isRename = !!this.data.table;
    readonly form = new FormGroup({
        name: new FormControl(this.data.table?.name ?? '', {
            nonNullable: true,
            validators: [Validators.required, Validators.maxLength(255)],
        }),
        description: new FormControl(this.data.table?.description ?? '', { nonNullable: true }),
    });

    private readonly dialogRef = inject<DialogRef<PersistenceTable | null>>(DialogRef);
    private readonly persistenceTablesApi = inject(PersistenceTablesApiService);
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
        const request$: Observable<PersistenceTable> = this.data.table
            ? this.persistenceTablesApi.updateTable(this.data.table.id, body)
            : this.persistenceTablesApi.createTable(body);

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
