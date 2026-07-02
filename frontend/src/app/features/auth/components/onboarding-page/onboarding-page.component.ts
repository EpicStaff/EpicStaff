import { HttpErrorResponse } from '@angular/common/http';
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

import { AuthService } from '../../../../services/auth/auth.service';
import { ToastService } from '../../../../services/notifications';
import { OrganizationsStorageService } from '../../../role-base-access/services/admin/organizations-storage.service';

@Component({
    selector: 'app-onboarding-page',
    imports: [
        ReactiveFormsModule,
        ButtonComponent,
        CustomInputComponent,
        AppSvgIconComponent,
        ValidationErrorsComponent,
    ],
    templateUrl: './onboarding-page.component.html',
    styleUrls: ['./onboarding-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OnboardingPageComponent {
    private router = inject(Router);
    private authService = inject(AuthService);
    private organizationsStorageService = inject(OrganizationsStorageService);
    private destroyRef = inject(DestroyRef);
    private toast = inject(ToastService);

    step = signal<1 | 2>(1);
    orgNameControl = new FormControl('', {
        nonNullable: true,
        validators: [Validators.required, Validators.minLength(3), Validators.maxLength(50)],
    });

    onContinue(): void {
        if (this.orgNameControl.invalid) {
            this.orgNameControl.markAsTouched();
            return;
        }
        const id = this.authService.defaultOrgId();

        if (!id) return;

        const dto = { name: this.orgNameControl.getRawValue() };
        this.organizationsStorageService
            .updateOrganization(id, dto)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.step.set(2),
                error: (err: HttpErrorResponse) => this.toast.error(err.error?.message),
            });

        this.step.set(2);
    }

    onStartWorking(): void {
        sessionStorage.removeItem('needs_onboarding');
        void this.router.navigate(['/projects']);
    }

    onSetupOrganizations(): void {
        sessionStorage.removeItem('needs_onboarding');
        void this.router.navigate(['/workspace/organizations']);
    }
}
