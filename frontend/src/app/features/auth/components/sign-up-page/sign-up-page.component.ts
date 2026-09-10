import { HttpErrorResponse } from '@angular/common/http';
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
import { ServerErrorsDirective, ServerErrorsRef } from '@shared/directives';
import { notNumericOnlyValidator, strictEmailValidator } from '@shared/form-validators';
import { HttpStatus } from '@shared/models';
import { forkJoin, timer } from 'rxjs';

import { AuthService } from '../../../../services/auth/auth.service';
import { ToastService } from '../../../../services/notifications';

type PageState = 'form' | 'loading' | 'success';

@Component({
    selector: 'app-sign-up',
    imports: [
        ReactiveFormsModule,
        ButtonComponent,
        CustomInputComponent,
        PasswordStrengthComponent,
        ValidationErrorsComponent,
        CheckboxComponent,
        AppSvgIconComponent,
        ServerErrorsDirective,
    ],
    templateUrl: './sign-up-page.component.html',
    styleUrls: ['./sign-up-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SignUpPageComponent {
    private readonly authService = inject(AuthService);
    private readonly router = inject(Router);
    private readonly toast = inject(ToastService);

    readonly serverErrorsRef = new ServerErrorsRef();

    readonly termsControl = new FormControl(false);

    readonly form = new FormGroup({
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

    readonly state = signal<PageState>('form');

    get password(): string {
        return this.form.get('password')!.value;
    }

    onSubmit(): void {
        this.serverErrorsRef.clear();
        this.form.markAllAsTouched();
        if (this.form.invalid || !this.termsControl.value) return;

        this.state.set('loading');

        const { email, password } = this.form.getRawValue();

        forkJoin([this.authService.runSetup({ email, password }), timer(1000)]).subscribe({
            next: ([resp]) => {
                this.authService.storeAccessToken(resp.access);
                this.state.set('success');
                timer(1000).subscribe(() => {
                    void this.router.navigate(['/onboarding']);
                });
            },
            error: (err: HttpErrorResponse) => {
                this.state.set('form');
                if (err.validationErrors?.length) {
                    this.serverErrorsRef.setErrors(err.validationErrors);
                    return;
                }
                if (err.status === HttpStatus.Conflict) {
                    this.toast.error(err.error?.message ?? 'Conflict');
                    return;
                }
                this.toast.error('Something went wrong. Please try again.');
            },
        });
    }

    navToLogin(): void {
        void this.router.navigate(['/login']);
    }
}
