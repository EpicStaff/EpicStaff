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
    HelpTooltipComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { TooltipOnOverflowDirective } from '@shared/directives';
import { extractHttpErrorMessage } from '@shared/utils';
import { Observable } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import {
    CreateVenvRequest,
    Venv,
    VENV_LIBRARY_SPECIFICATION_PATTERN,
    VENV_LIBRARY_VERSION_PATTERN,
    VenvLib,
} from '../../models/venv.model';
import { VenvsApiService } from '../../services/venvs-api.service';

export interface VenvDialogData {
    venv?: Venv;
}

interface LibraryRowGroup {
    name: FormControl<string>;
    description: FormControl<string>;
    // The installed version: a pin when the user types one, otherwise what the last build resolved.
    version: FormControl<string>;
    // The whole PEP 440 specifier set, stored and sent verbatim.
    specification: FormControl<string>;
}

@Component({
    selector: 'app-venv-dialog',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        HelpTooltipComponent,
        ValidationErrorsComponent,
        ButtonComponent,
        AppSvgIconComponent,
        MatTooltipModule,
        TooltipOnOverflowDirective,
    ],
    templateUrl: './venv-dialog.component.html',
    styleUrls: ['./venv-dialog.component.scss'],
})
export class VenvDialogComponent {
    readonly isSubmitting = signal(false);

    readonly data = inject<VenvDialogData | null>(DIALOG_DATA, { optional: true }) ?? {};
    readonly isEdit = !!this.data.venv;
    readonly title = computed(() => (this.isEdit ? 'Edit Venv' : 'Create Venv'));
    readonly submitLabel = computed(() => {
        if (this.isSubmitting()) return this.isEdit ? 'Saving...' : 'Creating...';
        return this.isEdit ? 'Save' : 'Create Venv';
    });

    readonly form = new FormGroup({
        name: new FormControl('', {
            nonNullable: true,
            validators: [Validators.required, Validators.maxLength(255)],
        }),
        libs: new FormArray<FormGroup<LibraryRowGroup>>([]),
    });

    protected readonly versionHint =
        'The version installed now. Clear it to let the next build pick one from the specification.';
    // Rendered with the line breaks intact: see `.venv-specifier-tooltip` in styles/_material.scss.
    protected readonly specificationHint = [
        'Which versions a build may install. Combine clauses with commas, e.g. !=1.2,>=1.0,<=1.8.',
        '',
        '==  exactly this version (==1.2.* allows any release of 1.2)',
        '!=  any version except this one',
        '>=  this version or newer',
        '<=  this version or older',
        '>   newer than this version',
        '<   older than this version',
        '~=  newer, but only within the last part you wrote (~=1.4 allows 1.5, not 2.0)',
    ].join('\n');

    private readonly dialogRef = inject<DialogRef<Venv | null>>(DialogRef);
    private readonly venvsApi = inject(VenvsApiService);
    private readonly toastService = inject(ToastService);
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

    removeAllLibraries(): void {
        this.libs.clear();
    }

    submit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }
        if (this.isSubmitting()) return;

        this.isSubmitting.set(true);
        const body = this.buildPayload();
        const request$: Observable<Venv> = this.data.venv
            ? this.venvsApi.updateVenv(this.data.venv.id, body)
            : this.venvsApi.createVenv(body);

        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (venv) => this.dialogRef.close(venv),
            error: (error: HttpErrorResponse) => {
                this.isSubmitting.set(false);
                this.toastService.error(extractHttpErrorMessage(error));
            },
        });
    }

    cancel(): void {
        this.dialogRef.close(null);
    }

    protected versionErrorMessage(row: FormGroup<LibraryRowGroup>): string | null {
        const version = row.controls.version;
        if (!version.touched || !version.hasError('pattern')) return null;
        return 'Not a valid version, e.g. 2.31.0';
    }

    // Whether the version actually satisfies the specification is PEP 440 ordering: the sandbox
    // service decides that and rejects the pair, naming both values.
    protected specificationErrorMessage(row: FormGroup<LibraryRowGroup>): string | null {
        const specification = row.controls.specification;
        if (!specification.touched || !specification.hasError('pattern')) return null;
        return 'Not a valid specifier set, e.g. >=1.0,<2.0';
    }

    private createLibraryRow(lib?: VenvLib): FormGroup<LibraryRowGroup> {
        return new FormGroup<LibraryRowGroup>({
            name: new FormControl(lib?.name ?? '', {
                nonNullable: true,
                validators: [Validators.required],
            }),
            description: new FormControl(lib?.description ?? '', { nonNullable: true }),
            version: new FormControl(lib?.version ?? '', {
                nonNullable: true,
                validators: [Validators.pattern(VENV_LIBRARY_VERSION_PATTERN)],
            }),
            specification: new FormControl(lib?.specification ?? '', {
                nonNullable: true,
                validators: [Validators.pattern(VENV_LIBRARY_SPECIFICATION_PATTERN)],
            }),
        });
    }

    private buildPayload(): CreateVenvRequest {
        const { name, libs } = this.form.getRawValue();
        return {
            name,
            libs: libs.map((row) => {
                const version = row.version.trim();
                return {
                    name: row.name.trim(),
                    specification: row.specification.trim(),
                    version: version || null,
                    description: row.description.trim() || null,
                };
            }),
        };
    }
}
