import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { DialogRef, DIALOG_DATA } from '@angular/cdk/dialog';
import { finalize } from 'rxjs/operators';

import { AppIconComponent } from '../../../../../shared/components/app-icon/app-icon.component';
import { CustomInputComponent } from '../../../../../shared/components/form-input/form-input.component';
import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { ToggleSwitchComponent } from '../../../../../shared/components/form-controls/toggle-switch/toggle-switch.component';
import { LLM_Provider } from '../../../models/LLM_provider.model';
import { LLM_Model } from '../../../models/llms/LLM.model';
import { LLM_Models_Service } from '../../../services/llms/LLM_models.service';
import { getProviderIconPath } from '../../../utils/get-provider-icon';
import { ToastService } from '../../../../../services/notifications/toast.service';

export interface CreateLlmModelDialogData {
    provider: LLM_Provider;
}

@Component({
    selector: 'app-create-llm-model-modal',
    standalone: true,
    imports: [
        CommonModule,
        ReactiveFormsModule,
        AppIconComponent,
        CustomInputComponent,
        ButtonComponent,
        ToggleSwitchComponent,
    ],
    templateUrl: './create-llm-model-modal.component.html',
    styleUrls: ['./create-llm-model-modal.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CreateLlmModelModalComponent {
    private dialogRef = inject(DialogRef);
    private dialogData = inject<CreateLlmModelDialogData>(DIALOG_DATA);
    private fb = inject(FormBuilder);
    private modelsService = inject(LLM_Models_Service);
    private toastService = inject(ToastService);

    isSubmitting = signal(false);

    form = this.fb.group({
        name: ['', Validators.required],
        baseUrl: ['', Validators.pattern(/^$|^https?:\/\/.+/i)],
        deploymentId: [''],
        apiVersion: [''],
        isVisible: [true],
    });

    provider = this.dialogData.provider;
    getProviderIcon = getProviderIconPath;

    onClose(): void {
        this.dialogRef.close(null);
    }

    onSubmit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }

        const value = this.form.getRawValue();
        this.isSubmitting.set(true);

        this.modelsService
            .createModel({
                name: (value.name || '').trim(),
                base_url: value.baseUrl?.trim() || null,
                deployment_id: value.deploymentId?.trim() || null,
                api_version: value.apiVersion?.trim() || null,
                llm_provider: this.provider.id,
                is_visible: !!value.isVisible,
                is_custom: true,
                predefined: false,
            })
            .pipe(finalize(() => this.isSubmitting.set(false)))
            .subscribe({
                next: (created: LLM_Model) => {
                    this.dialogRef.close(created);
                },
                error: (error) => {
                    this.toastService.error(this.extractApiErrorMessage(error));
                },
            });
    }

    private extractApiErrorMessage(error: unknown): string {
        const fallback = 'Failed to create model.';
        const httpError = error as { error?: unknown; message?: string };
        const payload = httpError?.error;

        if (typeof payload === 'string' && payload.trim()) {
            return payload;
        }

        if (payload && typeof payload === 'object') {
            const entries = Object.entries(payload as Record<string, unknown>);
            if (entries.length > 0) {
                const [field, value] = entries[0];
                const normalized = Array.isArray(value) ? value[0] : value;
                if (typeof normalized === 'string' && normalized.trim()) {
                    return `${field}: ${normalized}`;
                }
            }
        }

        if (httpError?.message) {
            return httpError.message;
        }

        return fallback;
    }
}

