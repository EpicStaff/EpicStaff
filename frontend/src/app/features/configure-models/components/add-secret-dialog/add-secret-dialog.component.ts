import { DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AbstractControl,
    FormBuilder,
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
    TextareaComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { EnterSubmitDirective } from '@shared/directives';
import { notWhitespaceValidator } from '@shared/form-validators';
import { Secret } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import { extractHttpErrorMessage, isAllowedSecretName } from '@shared/utils';

// The shared secret-name rule, identical to the server's: the name is inserted into Python code, also inside strings.
// An error of its own rather than `Validators.pattern`, whose message does not say which characters a name may use.
function secretNameValidator(control: AbstractControl): ValidationErrors | null {
    const value: unknown = control.value;
    if (typeof value !== 'string' || value === '') return null;
    return isAllowedSecretName(value) ? null : { secretName: true };
}

@Component({
    selector: 'app-add-secret-dialog',
    templateUrl: './add-secret-dialog.component.html',
    styleUrls: ['./add-secret-dialog.component.scss'],
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        TextareaComponent,
        ButtonComponent,
        ValidationErrorsComponent,
        AppSvgIconComponent,
        MatTooltipModule,
        EnterSubmitDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddSecretDialogComponent {
    private readonly fb = inject(FormBuilder);
    private readonly dialogRef = inject(DialogRef<Secret | null>);
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly form: FormGroup = this.fb.group({
        // Checked here as well as on the server so the error shows before the request instead of after it.
        name: ['', [Validators.required, notWhitespaceValidator(), secretNameValidator]],
        value: ['', Validators.required],
    });

    public readonly isSubmitting = signal<boolean>(false);
    public readonly errorMessage = signal<string | null>(null);

    public onCancel(): void {
        this.dialogRef.close(null);
    }

    public onSubmit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }

        this.isSubmitting.set(true);
        this.errorMessage.set(null);

        this.secretsStorageService
            .createSecret(this.form.value)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (secret) => {
                    this.isSubmitting.set(false);
                    this.dialogRef.close(secret);
                },
                error: (err: HttpErrorResponse) => {
                    this.isSubmitting.set(false);
                    this.errorMessage.set(extractHttpErrorMessage(err));
                },
            });
    }
}
