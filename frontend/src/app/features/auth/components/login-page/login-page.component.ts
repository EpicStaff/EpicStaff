import { CommonModule } from '@angular/common';
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
import { strictEmailValidator } from '@shared/form-validators';
import { interval, take } from 'rxjs';

import { AuthService } from '../../../../services/auth/auth.service';

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

    form = new FormGroup({
        email: new FormControl('', { nonNullable: true, validators: [Validators.required, strictEmailValidator()] }),
        password: new FormControl('', {
            nonNullable: true,
            validators: [Validators.required, Validators.minLength(8)],
        }),
        rememberMe: new FormControl(false, { nonNullable: true }),
    });

    loading = false;
    serverError = signal<string | null>('');
    throttleSecondsLeft = signal(0);

    ngOnInit(): void {
        this.form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.serverError.set(null);
        });
    }

    onSubmit(): void {
        if (this.form.invalid) return;

        this.loading = true;
        this.serverError.set(null);

        const email = this.form.getRawValue().email.toString();
        const password = this.form.getRawValue().password.toString();
        const rememberMe = this.form.getRawValue().rememberMe;
        this.authService
            .login(email, password, rememberMe)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl') || '/projects';
                    void this.router.navigateByUrl(returnUrl);
                },
                error: (err) => {
                    this.loading = false;
                    if (err.error.status_code === 429) {
                        this.handleThrottleError(err?.error?.message);
                        return;
                    }
                    this.serverError.set(err?.error?.message || 'Login failed. Please try again.');
                },
                complete: () => {
                    this.loading = false;
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
                complete: () => {
                    this.serverError.set(null);
                    this.throttleSecondsLeft.set(0);
                },
            });
    }

    navToSignUp(): void {
        void this.router.navigateByUrl('sign-up');
    }
}
