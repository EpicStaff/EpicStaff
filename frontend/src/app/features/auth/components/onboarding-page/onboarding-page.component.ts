import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AppSvgIconComponent, ButtonComponent, CustomInputComponent } from '@shared/components';

@Component({
    selector: 'app-onboarding-page',
    imports: [CommonModule, ReactiveFormsModule, ButtonComponent, CustomInputComponent, AppSvgIconComponent],
    templateUrl: './onboarding-page.component.html',
    styleUrls: ['./onboarding-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OnboardingPageComponent {
    private readonly router = inject(Router);

    step = signal<1 | 2>(1);
    orgNameControl = new FormControl('');

    onContinue(): void {
        if (this.orgNameControl.invalid) {
            this.orgNameControl.markAsTouched();
            return;
        }
        this.step.set(2);
    }

    onStartWorking(): void {
        sessionStorage.removeItem('needs_onboarding');
        void this.router.navigate(['/projects']);
    }

    onSetupOrganizations(): void {
        sessionStorage.removeItem('needs_onboarding');
        void this.router.navigate(['/projects']);
    }
}
