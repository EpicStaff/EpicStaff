import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CheckboxComponent,
    CustomInputComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { ServerErrorsDirective, ServerErrorsRef } from '@shared/directives';
import { strictEmailValidator } from '@shared/form-validators';
import { HttpStatus } from '@shared/models';
import { getRetryAfterSeconds } from '@shared/utils';
import { interval, Subscription, take } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { AuthService } from '../../../../services/auth/auth.service';
import { ToastService } from '../../../../services/notifications';

const REMEMBER_ME_STORAGE_KEY = 'auth.rememberMe';
// Shown when a 429 carries no readable Retry-After and no server message, so a throttled login is never silent.
const LOGIN_THROTTLED_FALLBACK_MESSAGE = 'Too many login attempts. Please try again later.';

@Component({
    selector: 'app-login-page',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        ValidationErrorsComponent,
        ButtonComponent,
        CheckboxComponent,
        AppSvgIconComponent,
        ServerErrorsDirective,
    ],
    templateUrl: './login-page.component.html',
    styleUrls: ['./login-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoginPageComponent implements OnInit {
    private readonly authService = inject(AuthService);
    private readonly router = inject(Router);
    private readonly route = inject(ActivatedRoute);
    private readonly destroyRef = inject(DestroyRef);
    private readonly toast = inject(ToastService);

    readonly serverErrorsRef = new ServerErrorsRef();

    readonly form = new FormGroup({
        email: new FormControl('', { nonNullable: true, validators: [Validators.required, strictEmailValidator()] }),
        password: new FormControl('', {
            nonNullable: true,
            validators: [Validators.required, Validators.minLength(8)],
        }),
        rememberMe: new FormControl(this.readStoredRememberMe(), { nonNullable: true }),
    });

    readonly loading = signal(false);
    readonly throttleSecondsLeft = signal(0);

    private throttleCountdown: Subscription | null = null;

    ngOnInit() {
        this.authService
            .getStatus()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((status) => {
                if (status.needs_setup) {
                    this.toast.info('You need to have at least one account to login');
                    void this.router.navigate(['/sign-up']);
                }
            });
    }

    onSubmit(): void {
        this.form.markAllAsTouched();
        // Enter submits the form even while the button is disabled, so the in-flight and countdown guards live here too.
        if (this.form.invalid || this.loading() || this.throttleSecondsLeft() > 0) return;

        this.loading.set(true);
        this.serverErrorsRef.clear();

        const { email, password, rememberMe } = this.form.getRawValue();
        this.persistRememberMe(rememberMe);

        this.authService
            .login(email, password, rememberMe)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loading.set(false))
            )
            .subscribe({
                next: () => {
                    const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl') || '/';
                    void this.router.navigateByUrl(returnUrl);
                },
                error: (err: HttpErrorResponse) => {
                    if (err.status === HttpStatus.TooManyRequests) {
                        this.handleThrottleError(err);
                        return;
                    }
                    if (err.validationErrors?.length) {
                        this.serverErrorsRef.setErrors(err.validationErrors);
                        return;
                    }
                    // Login failure on bad credentials — show as form-level error.
                    this.serverErrorsRef.setErrors([
                        { field: '', value: '', reason: err.error?.message ?? 'Login failed. Please try again.' },
                    ]);
                },
            });
    }

    navToSignUp(): void {
        void this.router.navigateByUrl('sign-up');
    }

    navToForgotPassword(): void {
        void this.router.navigateByUrl('forgot-password');
    }

    private handleThrottleError(err: HttpErrorResponse): void {
        const seconds = getRetryAfterSeconds(err);
        if (!seconds) {
            this.serverErrorsRef.setErrors([
                { field: '', value: '', reason: err.error?.message ?? LOGIN_THROTTLED_FALLBACK_MESSAGE },
            ]);
            return;
        }

        this.throttleCountdown?.unsubscribe();
        this.throttleSecondsLeft.set(seconds);
        this.throttleCountdown = interval(1000)
            .pipe(take(seconds), takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.throttleSecondsLeft.update((secondsLeft) => secondsLeft - 1),
                complete: () => this.throttleSecondsLeft.set(0),
            });
    }

    private readStoredRememberMe(): boolean {
        return localStorage.getItem(REMEMBER_ME_STORAGE_KEY) === 'true';
    }

    private persistRememberMe(value: boolean): void {
        localStorage.setItem(REMEMBER_ME_STORAGE_KEY, String(value));
    }
}
