import { DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CopyFieldComponent,
    CustomInputComponent,
    InputNumberComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { notWhitespaceValidator } from '@shared/form-validators';
import { finalize } from 'rxjs/operators';

import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';

@Component({
    selector: 'app-create-api-key-dialog',
    templateUrl: './create-api-key-dialog.component.html',
    styleUrls: ['./create-api-key-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        AppSvgIconComponent,
        ButtonComponent,
        ValidationErrorsComponent,
        CustomInputComponent,
        ReactiveFormsModule,
        InputNumberComponent,
        SelectComponent,
        CopyFieldComponent,
    ],
})
export class CreateApiKeyDialogComponent {
    private readonly dialogRef = inject(DialogRef<boolean>);
    private readonly destroyRef = inject(DestroyRef);
    private readonly profileService = inject(ProfileService);
    private readonly toast = inject(ToastService);

    readonly step = signal<'pending' | 'created'>('pending');
    readonly loading = signal(false);
    readonly copiedToClipboard = signal(false);
    readonly showStepper = signal(false);

    protected apiKey = '';
    protected defaultExpirationValue: number = 90;
    protected expirationSelectItems: SelectItem[] = [
        {
            name: '30 days',
            value: 30,
        },
        {
            name: '60 days',
            value: 60,
        },
        {
            name: '90 days',
            value: 90,
        },
        {
            name: 'Custom...',
            value: 'custom',
        },
        {
            name: 'Never',
            value: 'never',
        },
    ];

    form: FormGroup = new FormGroup({
        name: new FormControl('', [
            Validators.required,
            Validators.minLength(3),
            Validators.maxLength(30),
            notWhitespaceValidator(),
        ]),
        expires_in_days: new FormControl(this.defaultExpirationValue, [Validators.min(1), Validators.max(3650)]),
    });

    onExpirationChange(value: unknown): void {
        switch (typeof value) {
            case 'number':
                this.showStepper.set(false);
                this.form.get('expires_in_days')?.setValue(value);
                return;
            case 'string':
                if (value === 'custom') {
                    this.showStepper.set(true);
                    this.form.get('expires_in_days')?.setValue(90);
                } else {
                    this.showStepper.set(false);
                    this.form.get('expires_in_days')?.setValue(null);
                }
                return;
            default:
                return;
        }
    }

    onCreate(): void {
        if (this.form.invalid) return;

        const value = this.form.getRawValue();

        this.loading.set(true);
        this.profileService
            .createApiKey(value)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loading.set(false))
            )
            .subscribe({
                next: (key) => {
                    this.apiKey = key.api_key;
                    this.step.set('created');
                },
                error: (err: HttpErrorResponse) => {
                    this.toast.error(err.error.message);
                },
            });
    }

    onClose(): void {
        this.dialogRef.close();
    }
}
