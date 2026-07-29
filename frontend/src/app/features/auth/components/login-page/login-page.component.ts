import { CommonModule } from '@angular/common';
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
import { interval, take } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { AuthService } from '../../../../services/auth/auth.service';
import { ToastService } from '../../../../services/notifications';

@Component({
    selector: 'app-login-page',
    imports: [
        CommonModule,
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
        rememberMe: new FormControl(false, { nonNullable: true }),
    });

    readonly loading = signal(false);
    readonly throttleSecondsLeft = signal(0);

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
        if (this.form.invalid) return;

        this.loading.set(true);
        this.serverErrorsRef.clear();

        const { email, password, rememberMe } = this.form.getRawValue();

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
                        this.handleThrottleError(err.error?.message);
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

    handleThrottleError(message: string): void {
        const seconds = Math.ceil(parseFloat(message.split(':')[1]) || 0);
        this.throttleSecondsLeft.set(seconds);

        interval(1000)
            .pipe(take(seconds), takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.throttleSecondsLeft.update((v) => v - 1),
                complete: () => this.throttleSecondsLeft.set(0),
            });
    }

    navToSignUp(): void {
        void this.router.navigateByUrl('sign-up');
    }

    navToForgotPassword(): void {
        void this.router.navigateByUrl('forgot-password');
    }
}
