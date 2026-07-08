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
import { switchMap } from 'rxjs';

import { AuthService } from '../../../../services/auth/auth.service';
import { ProfileService } from '../../../../services/auth/profile.service';
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
    private readonly router = inject(Router);
    private readonly authService = inject(AuthService);
    private readonly organizationsStorageService = inject(OrganizationsStorageService);
    private readonly currentUserService = inject(ProfileService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly toast = inject(ToastService);

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
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                // Update user memberships after org name was changed
                switchMap(() => this.currentUserService.getCurrentUser())
            )
            .subscribe({
                next: () => this.step.set(2),
                error: (err: HttpErrorResponse) => this.toast.error(err.error?.message),
            });
    }

    onStartWorking(): void {
        this.authService.defaultOrgId.set(null);
        void this.router.navigate(['/projects']);
    }

    onSetupOrganizations(): void {
        this.authService.defaultOrgId.set(null);
        void this.router.navigate(['/workspace/organizations']);
    }
}
