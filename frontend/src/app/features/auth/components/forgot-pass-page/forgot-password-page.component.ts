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
import { finalize } from 'rxjs';

import { AuthService } from '../../../../services/auth/auth.service';
import { ToastService } from '../../../../services/notifications';

type PageState = 'request' | 'email-sent' | 'reset-unavailable';

// Mirrors the server's account-neutral wording, used when the response carries no detail.
const RESET_REQUESTED_FALLBACK_MESSAGE = 'If the email is registered, a reset link has been sent.';

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
    protected readonly resetRequestedMessage = signal(RESET_REQUESTED_FALLBACK_MESSAGE);
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
                finalize(() => this.loading.set(false))
            )
            .subscribe({
                next: (response) => {
                    // Without SMTP the server creates no reset link, so the page must not claim one was sent.
                    if (!response.smtp_configured) {
                        this.state.set('reset-unavailable');
                        return;
                    }
                    // The server answers identically for every email so it never reveals whether an account exists;
                    // the page shows that wording instead of promising a link was sent.
                    this.resetRequestedMessage.set(response.detail?.trim() || RESET_REQUESTED_FALLBACK_MESSAGE);
                    this.state.set('email-sent');
                },
                error: (err) => this.toast.error(err.error.message),
            });
    }

    navToLogin(): void {
        void this.router.navigate(['/login']);
    }
}
