import { DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Secret } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import { extractHttpErrorMessage } from '@shared/utils';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ValidationErrorsComponent } from '../../../../shared/components/app-validation-errors/validation-errors.component';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { TextareaComponent } from '../../../../shared/components/textarea/textarea.component';

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
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddSecretDialogComponent {
    private readonly fb = inject(FormBuilder);
    private readonly dialogRef = inject(DialogRef<Secret | null>);
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly form: FormGroup = this.fb.group({
        // Excludes characters that would inject HTML into the delete-confirmation dialog
        // ([innerHTML]-bound) or break the get_secret("name") string literal it's inserted into
        // by the code-editor autocomplete.
        name: ['', [Validators.required, Validators.pattern(/^[^<>"'&\\]*$/)]],
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
