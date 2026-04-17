import { CommonModule } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import {
    ButtonComponent,
    CheckboxComponent,
    CustomInputComponent,
    PasswordStrengthComponent,
    ValidationErrorsComponent,
} from '@shared/components';

import { AuthService } from '../../../../services/auth/auth.service';
import { SetupService } from '../../../../services/auth/setup.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';

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
})
export class SignUpPageComponent {
    private readonly setupService = inject(SetupService);
    private readonly authService = inject(AuthService);
    private readonly router = inject(Router);
    private readonly route = inject(ActivatedRoute);

    termsControl = new FormControl(false);

    form = new FormGroup({
        username: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
        password: new FormControl('', {
            nonNullable: true,
            validators: [Validators.required, Validators.minLength(8)],
        }),
        email: new FormControl('', { nonNullable: true }),
    });

    apiKey: string | null = null;
    loading = false;
    termsAccepted = false;
    serverError = signal<string | null>(null);

    get password(): string {
        return this.form.get('password')!.value;
    }

    onSubmit(): void {
        this.form.markAllAsTouched();
        if (this.form.invalid) return;

        this.serverError.set(null);
        this.loading = true;

        const payload = this.form.getRawValue();
        this.setupService.runSetup(payload).subscribe({
            next: (resp) => {
                this.authService.storeTokens({ access: resp.access, refresh: resp.refresh });
                this.loading = false;
                const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl') || '/projects';
                void this.router.navigateByUrl(returnUrl);
            },
            error: (err) => {
                this.loading = false;
                this.serverError.set(
                    err?.error?.detail || err?.error?.message || 'Registration failed. Please try again.'
                );
            },
            complete: () => {
                this.loading = false;
            },
        });
    }

    navToLogin(): void {
        this.router.navigate(['/login']);
    }
}
