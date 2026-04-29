import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CheckboxComponent,
    CustomInputComponent,
    PasswordStrengthComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { notNumericOnlyValidator, strictEmailValidator } from '@shared/form-validators';
import { ApiErrorItem } from '@shared/models';
import { forkJoin, timer } from 'rxjs';

import { AuthService } from '../../../../services/auth/auth.service';
import { ToastService } from '../../../../services/notifications';

type PageState = 'form' | 'loading' | 'success';

@Component({
    selector: 'app-sign-up',
    imports: [
        CommonModule,
        ReactiveFormsModule,
        ButtonComponent,
        CustomInputComponent,
        PasswordStrengthComponent,
        ValidationErrorsComponent,
        CheckboxComponent,
        AppSvgIconComponent,
    ],
    templateUrl: './sign-up-page.component.html',
    styleUrls: ['../login-page/login-page.component.scss', './sign-up-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SignUpPageComponent {
    private readonly authService = inject(AuthService);
    private readonly router = inject(Router);
    private readonly toast = inject(ToastService);

    termsControl = new FormControl(false);

    form = new FormGroup({
        email: new FormControl('', { nonNullable: true, validators: [Validators.required, strictEmailValidator()] }),
        password: new FormControl('', {
            nonNullable: true,
            validators: [
                Validators.required,
                Validators.minLength(8),
                Validators.maxLength(40),
                notNumericOnlyValidator(),
            ],
        }),
    });

    state = signal<PageState>('form');
    fieldErrors = signal<Record<string, string>>({});

    get password(): string {
        return this.form.get('password')!.value;
    }

    onSubmit(): void {
        this.fieldErrors.set({});
        this.form.markAllAsTouched();
        if (this.form.invalid) return;

        this.state.set('loading');

        const email = this.form.getRawValue().email.toString();
        const password = this.form.getRawValue().password.toString();

        forkJoin([this.authService.runSetup({ email, password }), timer(1000)]).subscribe({
            next: ([resp]) => {
                this.authService.storeTokens({ access: resp.access, refresh: resp.refresh });
                sessionStorage.setItem('needs_onboarding', 'true');
                this.state.set('success');
                timer(1000).subscribe(() => {
                    void this.router.navigate(['/onboarding']);
                });
            },
            error: (err) => {
                this.state.set('form');
                if (err.error.status_code === 409) {
                    this.toast.error(err.error.message);
                    return;
                }

                const errors: ApiErrorItem[] = err?.error?.errors ?? [];
                this.setApiErrors(errors);
            },
        });
    }

    private setApiErrors(errors: ApiErrorItem[]): void {
        this.fieldErrors.set(Object.fromEntries(errors.map(({ field, reason }) => [field, reason])));
    }

    navToLogin(): void {
        this.router.navigate(['/login']);
    }
}
