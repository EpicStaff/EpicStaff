import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { hasModifierKey } from '@angular/cdk/keycodes';
import { HttpErrorResponse } from '@angular/common/http';
import {
    afterNextRender,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    Injector,
    signal,
    viewChild,
    viewChildren,
} from '@angular/core';
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
    ValidationErrorsComponent,
} from '@shared/components';
import { EnterSubmitDirective } from '@shared/directives';
import { extractHttpErrorMessage } from '@shared/utils';
import { filter, Observable } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import {
    CreateVenvRequest,
    Venv,
    VENV_LIBRARY_SPECIFICATION_PATTERN,
    VENV_LIBRARY_VERSION_PATTERN,
    VENV_NAME_PATTERN,
    VenvLib,
} from '../../models/venv.model';
import { VenvsApiService } from '../../services/venvs-api.service';

export interface VenvDialogData {
    venv?: Venv;
}

// An error of its own rather than `Validators.pattern`, whose message does not say which
// characters a name may use.
function venvNameValidator(control: AbstractControl): ValidationErrors | null {
    const value: unknown = control.value;
    if (typeof value !== 'string' || value === '') return null;
    return VENV_NAME_PATTERN.test(value) ? null : { venvName: true };
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
        EnterSubmitDirective,
    ],
    templateUrl: './venv-dialog.component.html',
    styleUrls: ['./venv-dialog.component.scss'],
})
export class VenvDialogComponent {
    private readonly libraryNameInputs = viewChildren<ElementRef<HTMLInputElement>>('libraryNameInput');
    private readonly removeLibraryButtons = viewChildren<ElementRef<HTMLButtonElement>>('removeLibraryButton');
    private readonly addLibraryButton = viewChild.required<ElementRef<HTMLButtonElement>>('addLibraryButton');

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
            validators: [Validators.required, Validators.maxLength(255), venvNameValidator],
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
    private readonly injector = inject(Injector);

    constructor() {
        const venv = this.data.venv;
        if (venv) {
            this.form.controls.name.setValue(venv.name);
            for (const lib of venv.libs) {
                this.form.controls.libs.push(this.createLibraryRow(lib));
            }
        }
        // disableClose keeps a stray backdrop click from throwing the table away; Escape is asked for, so it cancels.
        this.dialogRef.keydownEvents
            .pipe(
                filter((event) => event.key === 'Escape' && !hasModifierKey(event) && !event.defaultPrevented),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((event) => {
                event.preventDefault();
                this.cancel();
            });
    }

    get libs(): FormArray<FormGroup<LibraryRowGroup>> {
        return this.form.controls.libs;
    }

    addLibrary(): void {
        this.libs.push(this.createLibraryRow());
        // The new row is where the next keystrokes go.
        afterNextRender(() => this.libraryNameInputs().at(-1)?.nativeElement.focus(), { injector: this.injector });
    }

    removeLibrary(index: number): void {
        this.libs.removeAt(index);
        // The removed row takes its focused button along: the focus moves to the row now in its place.
        afterNextRender(
            () => {
                const buttons = this.removeLibraryButtons();
                (buttons[Math.min(index, buttons.length - 1)] ?? this.addLibraryButton()).nativeElement.focus();
            },
            { injector: this.injector }
        );
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

    /** The field's name, and its whole value, which the narrow cell may cut. */
    protected cellTooltip(fieldName: string, value: string): string {
        return value ? `${fieldName}: ${value}` : fieldName;
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
