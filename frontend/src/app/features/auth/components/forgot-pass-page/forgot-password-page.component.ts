import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CustomInputComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { strictEmailValidator } from '@shared/form-validators';
import { finalize, tap } from 'rxjs';

import { AuthService } from '../../../../services/auth/auth.service';
import { ToastService } from '../../../../services/notifications';

type PageState = 'request' | 'email-sent' | 'reset-unavailable';

@Component({
    selector: 'app-forgot-password',
    templateUrl: './forgot-password-page.component.html',
    styleUrls: ['./forgot-password-page.component.scss'],
    imports: [
        ReactiveFormsModule,
        AppSvgIconComponent,
        ButtonComponent,
        CustomInputComponent,
        ValidationErrorsComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ForgotPasswordPageComponent {
    private authService = inject(AuthService);
    private router = inject(Router);
    private toast = inject(ToastService);
    private destroyRef = inject(DestroyRef);

    state = signal<PageState>('request');
    submittedEmail = signal('');
    loading = signal(false);

    readonly emailControl = new FormControl('', {
        nonNullable: true,
        validators: [Validators.required, strictEmailValidator()],
    });

    onRequestReset(): void {
        this.emailControl.markAsTouched();
        if (this.emailControl.invalid) return;
        const email = this.emailControl.getRawValue().toString();

        this.loading.set(true);
        this.authService
            .requestResetPassword({ email })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                tap(() => this.submittedEmail.set(this.emailControl.getRawValue())),
                finalize(() => this.loading.set(false))
            )
            .subscribe({
                // Without SMTP the server creates no reset link, so the page must not claim one was sent.
                next: (response) => this.state.set(response.smtp_configured ? 'email-sent' : 'reset-unavailable'),
                error: (err) => this.toast.error(err.error.message),
            });
    }

    navToLogin(): void {
        void this.router.navigate(['/login']);
    }
}
