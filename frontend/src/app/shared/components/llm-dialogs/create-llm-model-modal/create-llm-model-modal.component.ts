import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { EnterSubmitDirective } from '@shared/directives';
import { LLMModel, LLMProvider } from '@shared/models';
import { LlmModelsStorageService } from '@shared/services';
import { extractHttpErrorMessage, getProviderIconPath, isClientError } from '@shared/utils';
import { finalize } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { AppSvgIconComponent } from '../../app-svg-icon/app-svg-icon.component';
import { ValidationErrorsComponent } from '../../app-validation-errors/validation-errors.component';
import { ButtonComponent } from '../../buttons';
import { ErrorBannerComponent } from '../../error-banner/error-banner.component';
import { ToggleSwitchComponent } from '../../form-controls';
import { CustomInputComponent } from '../../form-input/form-input.component';
import { TooltipComponent } from '../../tooltip/tooltip.component';

export interface CreateLlmModelDialogData {
    provider: LLMProvider;
    model?: LLMModel;
}

@Component({
    selector: 'app-create-llm-model-modal',
    imports: [
        CommonModule,
        ReactiveFormsModule,
        MatTooltipModule,
        AppSvgIconComponent,
        CustomInputComponent,
        ButtonComponent,
        ErrorBannerComponent,
        ToggleSwitchComponent,
        TooltipComponent,
        ValidationErrorsComponent,
        EnterSubmitDirective,
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
    errorMessage = signal<string | null>(null);

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
        this.errorMessage.set(null);

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
              });

        request$.pipe(finalize(() => this.isSubmitting.set(false))).subscribe({
            next: (result: LLMModel) => {
                this.dialogRef.close(result);
            },
            error: (error: HttpErrorResponse) => {
                const fallback = this.isEditMode ? 'Failed to update model.' : 'Failed to create model.';
                if (isClientError(error)) {
                    this.errorMessage.set(this.clientErrorMessage(error, fallback));
                    return;
                }
                this.toastService.error(fallback);
            },
        });
    }

    private clientErrorMessage(error: HttpErrorResponse, fallback: string): string {
        if (error.error?.code === 'built_in_model_immutable') {
            return 'This model is a shared built-in and cannot be edited or deleted.';
        }
        return extractHttpErrorMessage(error, fallback);
    }
}
