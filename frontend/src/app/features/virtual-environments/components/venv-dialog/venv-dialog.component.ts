import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AbstractControl,
    FormArray,
    FormControl,
    FormGroup,
    ReactiveFormsModule,
    ValidationErrors,
    Validators,
} from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CustomInputComponent,
    HelpTooltipComponent,
    SelectComponent,
    SelectItem,
    SelectTriggerDirective,
    ValidationErrorsComponent,
} from '@shared/components';
import { TooltipOnOverflowDirective } from '@shared/directives';
import { extractHttpErrorMessage } from '@shared/utils';
import { merge, Observable, take } from 'rxjs';

import { CreateVenvRequest, Venv, VENV_LIBRARY_VERSION_PATTERN, VenvLib } from '../../models/venv.model';
import { VenvsApiService } from '../../services/venvs-api.service';

export interface VenvDialogData {
    venv?: Venv;
}

// PEP 440 version specifier operators, the only part of a specifier this MVP builds.
export type SpecifierOperator = '==' | '>=' | '<=' | '!=' | '~=' | '>' | '<';

const SPECIFIER_OPERATORS: SpecifierOperator[] = ['==', '>=', '<=', '!=', '~=', '>', '<'];
// Two-character operators first so ">=" is not read as ">" followed by "=...".
const SPECIFIER_OPERATORS_LONGEST_FIRST = [...SPECIFIER_OPERATORS].sort((a, b) => b.length - a.length);

const SPECIFIER_OPERATOR_LABELS: Record<SpecifierOperator, string> = {
    '==': 'Exactly',
    '>=': 'Greater or equal',
    '<=': 'Less or equal',
    '!=': 'Not equal',
    '~=': 'Compatible',
    '>': 'Greater than',
    '<': 'Less than',
};

interface LibraryRowGroup {
    name: FormControl<string>;
    operator: FormControl<SpecifierOperator>;
    version: FormControl<string>;
    // Unparseable stored specifier, sent back unchanged until the row is edited.
    preservedSpecification: FormControl<string | null>;
}

interface ParsedSpecification {
    operator: SpecifierOperator;
    version: string;
}

// PEP 440: "~=" needs at least two release segments.
function compatibleReleaseValidator(control: AbstractControl): ValidationErrors | null {
    const { operator, version } = control.value as ParsedSpecification;
    const trimmed = version.trim();
    if (operator !== '~=' || !trimmed) return null;
    return /^([0-9]+!)?[0-9]+\.[0-9]+/.test(trimmed) ? null : { compatibleRelease: true };
}

@Component({
    selector: 'app-venv-dialog',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        HelpTooltipComponent,
        SelectComponent,
        SelectTriggerDirective,
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
    readonly errorMessage = signal<string | null>(null);

    readonly data = inject<VenvDialogData | null>(DIALOG_DATA, { optional: true }) ?? {};
    readonly isEdit = !!this.data.venv;
    readonly title = computed(() => (this.isEdit ? 'Edit Venv' : 'Create Venv'));
    readonly submitLabel = computed(() => {
        if (this.isSubmitting()) return this.isEdit ? 'Saving...' : 'Creating...';
        return this.isEdit ? 'Save' : 'Create Venv';
    });

    readonly operatorItems: SelectItem<SpecifierOperator>[] = SPECIFIER_OPERATORS.map((operator) => ({
        name: `${operator} ${SPECIFIER_OPERATOR_LABELS[operator]}`,
        value: operator,
    }));
    protected readonly operatorLabels = SPECIFIER_OPERATOR_LABELS;

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

    versionErrorMessage(row: FormGroup<LibraryRowGroup>): string | null {
        const { operator, version } = row.controls;
        if (!operator.touched && !version.touched) return null;
        if (version.hasError('pattern')) return 'Not a valid version, e.g. 2.31.0';
        if (row.hasError('compatibleRelease')) return '"~=" needs at least two version parts, e.g. 1.4';
        return null;
    }

    private createLibraryRow(lib?: VenvLib): FormGroup<LibraryRowGroup> {
        const specification = lib?.specification ?? '';
        const parsed = this.parseSpecification(specification);
        const row = new FormGroup<LibraryRowGroup>(
            {
                name: new FormControl(lib?.name ?? '', {
                    nonNullable: true,
                    validators: [Validators.required],
                }),
                operator: new FormControl(parsed?.operator ?? '==', { nonNullable: true }),
                version: new FormControl(parsed?.version ?? '', {
                    nonNullable: true,
                    validators: [Validators.pattern(VENV_LIBRARY_VERSION_PATTERN)],
                }),
                preservedSpecification: new FormControl<string | null>(parsed ? null : specification),
            },
            { validators: compatibleReleaseValidator }
        );
        if (!parsed) {
            merge(row.controls.operator.valueChanges, row.controls.version.valueChanges)
                .pipe(take(1), takeUntilDestroyed(this.destroyRef))
                .subscribe(() => row.controls.preservedSpecification.setValue(null));
        }
        return row;
    }

    // Parses `specification`, not `lib.version`: that is the resolved version and would rewrite the user's constraint.
    private parseSpecification(specification: string): ParsedSpecification | null {
        const trimmed = specification.trim();
        if (!trimmed) return { operator: '==', version: '' };
        const operator = SPECIFIER_OPERATORS_LONGEST_FIRST.find((candidate) => trimmed.startsWith(candidate));
        if (!operator) return null;
        const version = trimmed.slice(operator.length).trim();
        return VENV_LIBRARY_VERSION_PATTERN.test(version) ? { operator, version } : null;
    }

    // `version` is the service-resolved lock, never user input.
    private buildPayload(): CreateVenvRequest {
        const { name, libs } = this.form.getRawValue();
        return {
            name,
            libs: libs.map((row) => {
                const version = row.version.trim();
                const built = version ? `${row.operator}${version}` : '';
                return {
                    name: row.name.trim(),
                    specification: row.preservedSpecification ?? built,
                    version: null,
                };
            }),
        };
    }
}
