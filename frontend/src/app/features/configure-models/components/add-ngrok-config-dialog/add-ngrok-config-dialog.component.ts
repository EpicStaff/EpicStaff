import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { CreateNgrokConfigRequest, GetNgrokConfigResponse } from '@shared/models';
import { NgrokConfigStorageService } from '@shared/services';

@Component({
    selector: 'app-create-ngrok-config-dialog',
    templateUrl: './add-ngrok-config-dialog.component.html',
    styleUrls: ['./add-ngrok-config-dialog.component.scss'],
    imports: [ReactiveFormsModule, CustomInputComponent, SelectComponent, ButtonComponent, ValidationErrorsComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddNgrokConfigDialogComponent implements OnInit {
    private fb = inject(FormBuilder);
    private dialogRef = inject(DialogRef);
    private ngrokStorageService = inject(NgrokConfigStorageService);
    private destroyRef = inject(DestroyRef);
    data: { config: GetNgrokConfigResponse | null; action: 'create' | 'update' } = inject(DIALOG_DATA);

    public isSubmitting = signal<boolean>(false);
    public errorMessage = signal<string | null>(null);

    form!: FormGroup;
    regionSelectItems: SelectItem[] = [
        {
            name: 'EU',
            value: 'eu',
        },
        {
            name: 'US',
            value: 'us',
        },
        {
            name: 'AP',
            value: 'ap',
        },
    ];

    ngOnInit() {
        this.initForm();

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onSubmit();
            }
        });
    }

    private initForm(): void {
        this.form = this.fb.group({
            name: [this.data.config?.name || '', Validators.required],
            auth_token: [this.data.config?.auth_token || '', Validators.required],
            region: [this.data.config?.region || 'eu'],
            domain: [this.data.config?.domain || ''],
        });
    }

    onSubmit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }
        this.isSubmitting.set(true);

        const formValue = this.form.value;
        const { config, action } = this.data;

        if (action === 'create') {
            this.createNgrokConfig(formValue);
        } else {
            this.updateNgrokConfig(config!.id, formValue);
        }
    }

    private createNgrokConfig(value: CreateNgrokConfigRequest): void {
        this.ngrokStorageService
            .createConfig(value)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.dialogRef.close(),
                error: (err) => {
                    this.errorMessage.set(
                        this.extractErrorMessage(err, 'Failed to create configuration. Please try again.')
                    );
                    this.isSubmitting.set(false);
                },
            });
    }

    private updateNgrokConfig(id: number, value: CreateNgrokConfigRequest): void {
        this.ngrokStorageService
            .updateConfigById(id, value)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.dialogRef.close(),
                error: (err) => {
                    this.errorMessage.set(
                        this.extractErrorMessage(err, 'Failed to update configuration. Please try again.')
                    );
                    this.isSubmitting.set(false);
                },
            });
    }

    private extractErrorMessage(err: unknown, fallback: string): string {
        const error = (err as { error?: { message?: unknown } } | null)?.error;
        const raw = error?.message;

        if (typeof raw === 'string') {
            const matches = [...raw.matchAll(/string=(['"])(.*?)\1/g)].map((m) => m[2]);
            if (matches.length) {
                return matches.join(' ');
            }
            return raw;
        }

        if (raw && typeof raw === 'object') {
            const parts: string[] = [];
            for (const value of Object.values(raw as Record<string, unknown>)) {
                if (Array.isArray(value)) {
                    parts.push(...value.map(String));
                } else if (value != null) {
                    parts.push(String(value));
                }
            }
            if (parts.length) {
                return parts.join(' ');
            }
        }

        return fallback;
    }

    onCancel(): void {
        this.dialogRef.close();
    }
}
