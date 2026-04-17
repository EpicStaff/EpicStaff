import { CommonModule } from '@angular/common';
import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import {
    ButtonComponent,
    CheckboxComponent,
    CustomInputComponent,
    ValidationErrorsComponent,
} from '@shared/components';

import { AuthService } from '../../../../services/auth/auth.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';

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
})
export class LoginPageComponent implements OnInit {
    private readonly authService = inject(AuthService);
    private readonly router = inject(Router);
    private readonly route = inject(ActivatedRoute);
    private readonly destroyRef = inject(DestroyRef);

    form = new FormGroup({
        username: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
        password: new FormControl('', {
            nonNullable: true,
            validators: [Validators.required, Validators.minLength(8)],
        }),
        rememberMe: new FormControl(false, { nonNullable: true }),
    });

    loading = false;
    serverError = signal<string | null>('');

    ngOnInit(): void {
        this.form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.serverError.set(null);
        });
    }

    onSubmit(): void {
        if (this.form.invalid) return;

        this.loading = true;
        this.serverError.set(null);

        const { username, password, rememberMe } = this.form.getRawValue();
        this.authService
            .login(username, password, rememberMe)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl') || '/projects';
                    void this.router.navigateByUrl(returnUrl);
                },
                error: (err) => {
                    this.loading = false;
                    this.serverError.set(err?.error?.message || 'Login failed. Please try again.');
                },
                complete: () => {
                    this.loading = false;
                },
            });
    }

    navToSignUp(): void {
        void this.router.navigateByUrl('sign-up');
    }
}
