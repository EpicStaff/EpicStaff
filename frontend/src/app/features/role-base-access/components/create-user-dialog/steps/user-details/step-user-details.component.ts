import { ChangeDetectionStrategy, Component, effect, inject, input } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    CustomInputComponent,
    HelpTooltipComponent,
    PasswordStrengthComponent,
    ToggleSwitchComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { notNumericOnlyValidator } from '@shared/form-validators';
import { map } from 'rxjs';

import { NormalizedUser } from '../../../../strategies/users/user-fetch.strategy';

@Component({
    selector: 'app-step-user-details',
    templateUrl: './step-user-details.component.html',
    styleUrls: ['./step-user-details.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        ValidationErrorsComponent,
        ToggleSwitchComponent,
        HelpTooltipComponent,
        PasswordStrengthComponent,
    ],
})
export class StepUserDetailsComponent {
    private fb = inject(FormBuilder);

    canToggleSuperadmin = input<boolean>(false);
    editMode = input<boolean>(false);
    userData = input<NormalizedUser | null>(null);

    form = this.fb.group({
        // full_name: ['', [Validators.required]],
        email: ['', [Validators.required, Validators.email]],
        password: new FormControl('', {
            nonNullable: true,
            validators: [
                Validators.required,
                Validators.minLength(8),
                Validators.maxLength(40),
                notNumericOnlyValidator(),
            ],
        }),
        superadmin: [false],
        picture: [null as File | null],
    });

    readonly isFormValid = toSignal(this.form.statusChanges.pipe(map(() => this.form.valid)), {
        initialValue: this.form.valid,
    });

    constructor() {
        effect(() => {
            const user = this.userData();
            if (this.editMode() && user) {
                this.form.patchValue({
                    // full_name: user.displayName,
                    email: user.email,
                    superadmin: user.isSuperadmin,
                });
                this.form.get('email')!.disable();
                this.form.get('password')!.clearValidators();
                this.form.get('password')!.updateValueAndValidity();
            }
        });
    }

    trimEmail(): void {
        const control = this.form.get('email');

        if (control?.value) {
            control.setValue(control.value.trim());
        }
    }

    get password(): string {
        return this.form.get('password')!.value;
    }
}
