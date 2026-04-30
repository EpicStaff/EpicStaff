import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CustomInputComponent,
    ToggleSwitchComponent,
    TooltipComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { LLMModel, LLMProvider } from '@shared/models';
import { LlmModelsStorageService } from '@shared/services';
import { getProviderIconPath } from '@shared/utils';
import { finalize } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';

export interface CreateLlmModelDialogData {
    provider: LLMProvider;
    model?: LLMModel;
}

@Component({
    selector: 'app-create-llm-model-modal',
    imports: [
        CommonModule,
        ReactiveFormsModule,
        AppSvgIconComponent,
        CustomInputComponent,
        ButtonComponent,
        ToggleSwitchComponent,
        TooltipComponent,
        ValidationErrorsComponent,
    ],
    templateUrl: './create-llm-model-modal.component.html',
    styleUrls: ['./create-llm-model-modal.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CreateLlmModelModalComponent implements OnInit {
    private dialogRef = inject(DialogRef);
    private dialogData = inject<CreateLlmModelDialogData>(DIALOG_DATA);
    private destroyRef = inject(DestroyRef);
    private fb = inject(FormBuilder);
    private modelsStorageService = inject(LlmModelsStorageService);
    private toastService = inject(ToastService);

    isEditMode = !!this.dialogData.model;
    isSubmitting = signal(false);

    form = this.fb.group({
        name: [this.dialogData.model?.name ?? '', Validators.required],
        baseUrl: [this.dialogData.model?.base_url ?? '', Validators.pattern(/^$|^https?:\/\/.+/i)],
        deploymentId: [this.dialogData.model?.deployment_id ?? ''],
        apiVersion: [this.dialogData.model?.api_version ?? ''],
        isVisible: [this.dialogData.model?.is_visible ?? true],
    });

    provider = this.dialogData.provider;
    getProviderIcon = getProviderIconPath;

    ngOnInit() {
        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onSubmit();
            }
        });
    }

    onClose(): void {
        this.dialogRef.close(null);
    }

    onSubmit(): void {
        if (this.form.invalid || this.isSubmitting()) {
            this.form.markAllAsTouched();
            return;
        }

        const value = this.form.getRawValue();
        this.isSubmitting.set(true);

        const request$ = this.isEditMode
            ? this.modelsStorageService.patchModel(this.dialogData.model!.id, {
                  name: (value.name || '').trim(),
                  base_url: value.baseUrl?.trim() || null,
                  deployment_id: value.deploymentId?.trim() || null,
                  api_version: value.apiVersion?.trim() || null,
                  is_visible: !!value.isVisible,
              })
            : this.modelsStorageService.createModel({
                  name: (value.name || '').trim(),
                  base_url: value.baseUrl?.trim() || null,
                  deployment_id: value.deploymentId?.trim() || null,
                  api_version: value.apiVersion?.trim() || null,
                  llm_provider: this.provider.id,
                  is_visible: !!value.isVisible,
                  is_custom: true,
                  predefined: false,
              });

        request$.pipe(finalize(() => this.isSubmitting.set(false))).subscribe({
            next: (result: LLMModel) => {
                this.dialogRef.close(result);
            },
            error: (error) => {
                this.toastService.error(this.extractApiErrorMessage(error));
            },
        });
    }

    private extractApiErrorMessage(error: unknown): string {
        const fallback = this.isEditMode ? 'Failed to update model.' : 'Failed to create model.';
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
