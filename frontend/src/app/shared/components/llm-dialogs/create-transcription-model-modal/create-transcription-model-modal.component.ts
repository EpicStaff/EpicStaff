import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { EnterSubmitDirective } from '@shared/directives';
import { GetRealtimeTranscriptionModelRequest, LLMProvider } from '@shared/models';
import { TranscriptionModelsStorageService } from '@shared/services';
import { extractErrorCode, extractHttpErrorMessage, getProviderIconPath } from '@shared/utils';
import { finalize } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { AppSvgIconComponent } from '../../app-svg-icon/app-svg-icon.component';
import { ValidationErrorsComponent } from '../../app-validation-errors/validation-errors.component';
import { ButtonComponent } from '../../buttons';
import { CustomInputComponent } from '../../form-input/form-input.component';
import { TooltipComponent } from '../../tooltip/tooltip.component';

export interface CreateTranscriptionModelDialogData {
    provider: LLMProvider;
    model?: GetRealtimeTranscriptionModelRequest;
}

@Component({
    selector: 'app-create-transcription-model-modal',
    imports: [
        CommonModule,
        ReactiveFormsModule,
        MatTooltipModule,
        AppSvgIconComponent,
        CustomInputComponent,
        ButtonComponent,
        TooltipComponent,
        ValidationErrorsComponent,
        EnterSubmitDirective,
    ],
    templateUrl: './create-transcription-model-modal.component.html',
    styleUrls: ['./create-transcription-model-modal.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CreateTranscriptionModelModalComponent {
    private dialogRef = inject(DialogRef);
    private dialogData = inject<CreateTranscriptionModelDialogData>(DIALOG_DATA);
    private destroyRef = inject(DestroyRef);
    private fb = inject(FormBuilder);
    private transcriptionModelsService = inject(TranscriptionModelsStorageService);
    private toastService = inject(ToastService);

    isEditMode = !!this.dialogData.model;

    isSubmitting = signal(false);

    form = this.fb.group({
        name: [this.dialogData.model?.name ?? '', Validators.required],
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

        const name = (value.name || '').trim();
        const request$ = this.isEditMode
            ? this.transcriptionModelsService.patchModel(this.dialogData.model!.id, { name })
            : this.transcriptionModelsService.createModel({ name, provider: this.provider.id });

        request$.pipe(finalize(() => this.isSubmitting.set(false))).subscribe({
            next: (result) => {
                this.dialogRef.close(result);
            },
            error: (error) => {
                this.toastService.error(this.extractApiErrorMessage(error));
            },
        });
    }

    private extractApiErrorMessage(error: unknown): string {
        const fallback = this.isEditMode ? 'Failed to update model.' : 'Failed to create model.';
        if (!(error instanceof HttpErrorResponse)) return fallback;
        if (extractErrorCode(error) === 'built_in_model_immutable') {
            return 'This model is a shared built-in and cannot be edited or deleted.';
        }
        return extractHttpErrorMessage(error, fallback);
    }
}
