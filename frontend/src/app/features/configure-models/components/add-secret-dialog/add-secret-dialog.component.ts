import { DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CustomInputComponent,
    TextareaComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { SecretsStorageService } from '@shared/services';
import { extractHttpErrorMessage } from '@shared/utils';

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
    private readonly dialogRef = inject(DialogRef<void>);
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly form: FormGroup = this.fb.group({
        name: ['', Validators.required],
        value: ['', Validators.required],
    });

    public readonly isSubmitting = signal<boolean>(false);
    public readonly errorMessage = signal<string | null>(null);

    public onCancel(): void {
        this.dialogRef.close();
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
                next: () => {
                    this.isSubmitting.set(false);
                    this.dialogRef.close();
                },
                error: (err: HttpErrorResponse) => {
                    this.isSubmitting.set(false);
                    this.errorMessage.set(extractHttpErrorMessage(err));
                },
            });
    }
}
