import { DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CustomInputComponent,
    PasswordStrengthComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { ServerErrorsDirective, ServerErrorsRef } from '@shared/directives';
import { notNumericOnlyValidator } from '@shared/form-validators';
import { finalize } from 'rxjs/operators';

import { AuthService } from '../../../../services/auth/auth.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';

type DialogStep = 'verify' | 'new-password';

@Component({
    selector: 'app-password-change-dialog',
    templateUrl: './password-change-dialog.component.html',
    styleUrls: ['./password-change-dialog.component.scss'],
    imports: [
        ReactiveFormsModule,
        AppSvgIconComponent,
        ButtonComponent,
        CustomInputComponent,
        PasswordStrengthComponent,
        ValidationErrorsComponent,
        ServerErrorsDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PasswordChangeDialogComponent {
    private readonly dialogRef = inject(DialogRef<boolean>);
    private readonly destroyRef = inject(DestroyRef);
    private readonly fb = inject(FormBuilder);
    private readonly profileService = inject(ProfileService);
    private readonly authService = inject(AuthService);
    private readonly toast = inject(ToastService);

    readonly step = signal<DialogStep>('verify');
    readonly loading = signal(false);

    private ticket = '';

    readonly verifyForm = this.fb.group({
        current_password: ['', [Validators.required, Validators.minLength(8)]],
    });
    readonly verifyErrorsRef = new ServerErrorsRef();

    readonly newPasswordForm = this.fb.group({
        new_password: [
            '',
            [Validators.required, Validators.minLength(8), Validators.maxLength(40), notNumericOnlyValidator()],
        ],
        confirm_password: ['', [Validators.required, Validators.minLength(8)]],
    });
    readonly newPasswordErrorsRef = new ServerErrorsRef();

    get newPassword(): string {
        return this.newPasswordForm.getRawValue().new_password || '';
    }

    get passwordsMatch(): boolean {
        return this.newPassword === this.newPasswordForm.getRawValue().confirm_password;
    }

    onVerify(): void {
        this.verifyForm.markAllAsTouched();
        if (this.verifyForm.invalid) return;

        this.loading.set(true);
        this.verifyErrorsRef.clear();

        this.profileService
            .requestPasswordChange({ current_password: this.verifyForm.getRawValue().current_password! })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loading.set(false))
            )
            .subscribe({
                next: ({ ticket }) => {
                    this.ticket = ticket;
                    this.step.set('new-password');
                },
                error: (err: HttpErrorResponse) => {
                    this.verifyErrorsRef.setErrors([
                        { field: 'current_password', value: '', reason: err.error?.message ?? 'Incorrect password.' },
                    ]);
                },
            });
    }

    onSubmit(): void {
        this.newPasswordForm.markAllAsTouched();
        if (this.newPasswordForm.invalid) return;

        if (!this.passwordsMatch) {
            this.newPasswordErrorsRef.setErrors([
                { field: 'confirm_password', value: '', reason: 'Passwords do not match.' },
            ]);
            return;
        }

        this.loading.set(true);
        this.newPasswordErrorsRef.clear();

        this.profileService
            .confirmPasswordChange({ ticket: this.ticket, new_password: this.newPassword })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loading.set(false))
            )
            .subscribe({
                next: (tokens) => {
                    this.toast.success('Password updated successfully.');
                    this.authService.storeAccessToken(tokens.access);
                    this.dialogRef.close(true);
                },
                error: (err: HttpErrorResponse) => {
                    if (err.validationErrors?.length) {
                        this.newPasswordErrorsRef.setErrors(err.validationErrors);
                    } else {
                        this.toast.error(err.error.message);
                    }
                },
            });
    }

    onCancel(): void {
        this.dialogRef.close(false);
    }
}
