import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CustomInputComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { extractHttpErrorMessage } from '@shared/utils';
import { Observable } from 'rxjs';

import { CreateVenvRequest, Venv, VenvLib } from '../../models/venv.model';
import { VenvsApiService } from '../../services/venvs-api.service';

export interface VenvDialogData {
    venv?: Venv;
}

// PEP 440 version specifier operators, the only part of a specifier this MVP builds.
export type SpecifierOperator = '==' | '>=' | '<=' | '!=' | '~=' | '>' | '<';

const SPECIFIER_OPERATORS: SpecifierOperator[] = ['==', '>=', '<=', '!=', '~=', '>', '<'];

interface LibraryRowGroup {
    name: FormControl<string>;
    operator: FormControl<SpecifierOperator>;
    version: FormControl<string>;
}

@Component({
    selector: 'app-venv-dialog',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        SelectComponent,
        ValidationErrorsComponent,
        ButtonComponent,
        AppSvgIconComponent,
        MatTooltipModule,
    ],
    templateUrl: './venv-dialog.component.html',
    styleUrls: ['./venv-dialog.component.scss'],
})
export class VenvDialogComponent {
    readonly isSubmitting = signal(false);
    readonly errorMessage = signal<string | null>(null);

    readonly data = inject<VenvDialogData | null>(DIALOG_DATA, { optional: true }) ?? {};
    readonly isEdit = !!this.data.venv;
    readonly title = computed(() => (this.isEdit ? 'Edit venv' : 'Create venv'));

    readonly operatorItems: SelectItem<SpecifierOperator>[] = SPECIFIER_OPERATORS.map((operator) => ({
        name: operator,
        value: operator,
    }));

    readonly form = new FormGroup({
        name: new FormControl('', {
            nonNullable: true,
            validators: [Validators.required, Validators.maxLength(255)],
        }),
        libs: new FormArray<FormGroup<LibraryRowGroup>>([]),
    });

    private readonly dialogRef = inject<DialogRef<Venv | null>>(DialogRef);
    private readonly venvsApi = inject(VenvsApiService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        const venv = this.data.venv;
        if (venv) {
            this.form.controls.name.setValue(venv.name);
            for (const lib of venv.libs) {
                this.form.controls.libs.push(this.createLibraryRow(lib));
            }
        }
    }

    get libs(): FormArray<FormGroup<LibraryRowGroup>> {
        return this.form.controls.libs;
    }

    addLibrary(): void {
        this.libs.push(this.createLibraryRow());
    }

    removeLibrary(index: number): void {
        this.libs.removeAt(index);
    }

    submit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }
        if (this.isSubmitting()) return;

        this.isSubmitting.set(true);
        this.errorMessage.set(null);
        const body = this.buildPayload();
        const request$: Observable<Venv> = this.data.venv
            ? this.venvsApi.updateVenv(this.data.venv.id, body)
            : this.venvsApi.createVenv(body);

        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (venv) => this.dialogRef.close(venv),
            error: (error: HttpErrorResponse) => {
                this.isSubmitting.set(false);
                this.errorMessage.set(extractHttpErrorMessage(error));
            },
        });
    }

    cancel(): void {
        this.dialogRef.close(null);
    }

    private createLibraryRow(lib?: VenvLib): FormGroup<LibraryRowGroup> {
        return new FormGroup<LibraryRowGroup>({
            name: new FormControl(lib?.name ?? '', {
                nonNullable: true,
                validators: [Validators.required],
            }),
            operator: new FormControl(this.operatorFromSpecification(lib?.specification), {
                nonNullable: true,
            }),
            version: new FormControl(lib?.version ?? '', { nonNullable: true }),
        });
    }

    private operatorFromSpecification(specification: string | undefined): SpecifierOperator {
        if (!specification) return '==';
        // Longest operators first so "==" is not shadowed by ">" etc.
        const match = [...SPECIFIER_OPERATORS]
            .sort((a, b) => b.length - a.length)
            .find((op) => specification.startsWith(op));
        return match ?? '==';
    }

    private buildPayload(): CreateVenvRequest {
        const { name, libs } = this.form.getRawValue();
        return {
            name,
            libs: libs.map((row) => {
                const version = row.version.trim();
                return {
                    name: row.name.trim(),
                    specification: version ? `${row.operator}${version}` : '',
                    version: version || null,
                };
            }),
        };
    }
}
