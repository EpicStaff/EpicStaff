import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { ActivatedRoute, Router } from '@angular/router';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CustomInputComponent,
    HintMessageComponent,
    PasswordStrengthComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { ServerErrorsDirective, ServerErrorsRef } from '@shared/directives';
import { notNumericOnlyValidator } from '@shared/form-validators';
import { finalize } from 'rxjs';

import { AuthService } from '../../../../services/auth/auth.service';
import { ToastService } from '../../../../services/notifications';

type PageState = 'invalid-token' | 'set-password' | 'success';

@Component({
    selector: 'app-reset-password-page',
    templateUrl: './reset-password-page.component.html',
    styleUrls: ['./reset-password-page.component.scss'],
    imports: [
        ReactiveFormsModule,
        AppSvgIconComponent,
        ButtonComponent,
        CustomInputComponent,
        HintMessageComponent,
        ValidationErrorsComponent,
        MatIconModule,
        PasswordStrengthComponent,
        ServerErrorsDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ResetPasswordPageComponent {
    private route = inject(ActivatedRoute);
    private authService = inject(AuthService);
    private destroyRef = inject(DestroyRef);
    private toast = inject(ToastService);
    private router = inject(Router);

    state = signal<PageState>('set-password');
    loading = signal(false);

    private token = '';
    readonly serverErrorsRef = new ServerErrorsRef();

    readonly form = new FormGroup({
        new_password: new FormControl('', {
            nonNullable: true,
            validators: [
                Validators.required,
                Validators.minLength(8),
                Validators.maxLength(40),
                notNumericOnlyValidator(),
            ],
        }),
    });

    constructor() {
        this.token = this.route.snapshot.queryParamMap.get('token') ?? '';

        if (!this.token) this.navToLogin();
    }

    get password(): string {
        return this.form.get('new_password')?.getRawValue();
    }

    onSubmit(): void {
        this.form.markAllAsTouched();
        if (this.form.invalid) return;

        const data = {
            token: this.token,
            new_password: this.password.toString(),
        };

        this.loading.set(true);
        this.authService
            .confirmResetPassword(data)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loading.set(false))
            )
            .subscribe({
                next: () => {
                    this.state.set('success');
                },
                error: (err) => {
                    if (err.validationErrors?.length) {
                        this.serverErrorsRef.setErrors(err.validationErrors);
                        return;
                    } else {
                        this.toast.error(err?.error.message);
                    }
                },
            });
    }

    navToLogin(): void {
        void this.router.navigateByUrl('/login');
    }
}
