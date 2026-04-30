import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { Component, DestroyRef, Inject, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    CreateTranscriptionConfigRequest,
    GetRealtimeTranscriptionModelRequest,
    GetTranscriptionConfigRequest,
    UpdateTranscriptionConfigRequest,
} from '@shared/models';
import { ApiGetResponse, RealtimeTranscriptionModelsService, TranscriptionConfigsService } from '@shared/services';

import { ToastService } from '../../../../../../../services/notifications/toast.service';

export interface AddTranscriptionConfigDialogData {
    providerId?: number;
    editConfig?: GetTranscriptionConfigRequest;
}

@Component({
    selector: 'app-add-transcription-config-dialog',
    standalone: true,
    imports: [CommonModule, ReactiveFormsModule],
    templateUrl: './add-transcription-config-dialog.component.html',
    styleUrls: ['./add-transcription-config-dialog.component.scss'],
})
export class AddTranscriptionConfigDialogComponent implements OnInit {
    transcriptionForm!: FormGroup;
    showApiKey = false;
    models: GetRealtimeTranscriptionModelRequest[] = [];
    submitting = false;
    private lastAutoCustomName: string | null = null;
    private destroyRef = inject(DestroyRef);

    constructor(
        private fb: FormBuilder,
        public dialogRef: DialogRef<GetTranscriptionConfigRequest>,
        private toastService: ToastService,
        private transcriptionConfigsService: TranscriptionConfigsService,
        private realtimeTranscriptionModelsService: RealtimeTranscriptionModelsService,
        @Inject(DIALOG_DATA) public data: AddTranscriptionConfigDialogData
    ) {}

    ngOnInit(): void {
        this.loadModels();
        this.initForm();
        this.setupModelSubscription();
        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onConfirm();
            }
        });
    }

    public get isEditMode(): boolean {
        return !!this.data?.editConfig;
    }

    private initForm(): void {
        const edit = this.data?.editConfig;
        this.transcriptionForm = this.fb.group({
            realtime_transcription_model: [edit?.realtime_transcription_model ?? null, Validators.required],
            custom_name: [edit?.custom_name ?? '', Validators.required],
            api_key: [edit?.api_key ?? '', Validators.required],
        });
        if (edit) {
            this.lastAutoCustomName = null;
        }
    }

    private setupModelSubscription(): void {
        this.transcriptionForm
            .get('realtime_transcription_model')
            ?.valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.updateCustomName());
    }

    showError(controlName: string): boolean {
        const control = this.transcriptionForm.get(controlName);
        return control ? control.invalid && (control.touched || control.dirty) : false;
    }

    toggleApiKeyVisibility(): void {
        this.showApiKey = !this.showApiKey;
    }

    loadModels(): void {
        this.realtimeTranscriptionModelsService
            .getAllModels()
            .subscribe((res: ApiGetResponse<GetRealtimeTranscriptionModelRequest>) => {
                this.models = res.results;
                this.updateCustomName();
            });
    }

    onConfirm(): void {
        if (!this.transcriptionForm.valid) {
            this.transcriptionForm.markAllAsTouched();
            return;
        }

        this.submitting = true;
        const formValue = this.transcriptionForm.value;

        if (this.isEditMode) {
            const update: UpdateTranscriptionConfigRequest = {
                id: this.data.editConfig!.id,
                realtime_transcription_model: formValue.realtime_transcription_model,
                api_key: formValue.api_key,
                custom_name: formValue.custom_name,
            };
            this.transcriptionConfigsService.updateTranscriptionConfig(update).subscribe({
                next: (updatedConfig: GetTranscriptionConfigRequest) => {
                    this.toastService.success(
                        `Transcription configuration "${updatedConfig.custom_name}" has been successfully updated`
                    );
                    this.dialogRef.close(updatedConfig);
                    this.submitting = false;
                },
                error: (error) => {
                    console.error('Error updating transcription config:', error);
                    this.toastService.error('Failed to update transcription configuration');
                    this.submitting = false;
                },
            });
            return;
        }

        const config: CreateTranscriptionConfigRequest = {
            realtime_transcription_model: formValue.realtime_transcription_model,
            api_key: formValue.api_key,
            custom_name: formValue.custom_name,
        };
        this.transcriptionConfigsService.createTranscriptionConfig(config).subscribe({
            next: (createdConfig: GetTranscriptionConfigRequest) => {
                this.toastService.success(
                    `Transcription configuration "${createdConfig.custom_name}" has been successfully created`
                );
                this.dialogRef.close(createdConfig);
                this.submitting = false;
            },
            error: (error) => {
                console.error('Error creating transcription config:', error);
                this.toastService.error('Failed to create transcription configuration');
                this.submitting = false;
            },
        });
    }

    onCancel(): void {
        this.dialogRef.close();
    }

    private updateCustomName(): void {
        const modelControl = this.transcriptionForm.get('realtime_transcription_model');
        const customNameControl = this.transcriptionForm.get('custom_name');

        if (!modelControl || !customNameControl) {
            return;
        }

        const modelId = modelControl.value;
        if (!modelId) {
            return;
        }

        const selectedModel = this.models.find((model) => model.id === modelId);
        if (!selectedModel) {
            return;
        }

        const currentName = customNameControl.value;
        const isKnownModelName = this.models.some((model) => model.name === currentName);
        const isAutoName = !currentName || currentName === this.lastAutoCustomName || isKnownModelName;
        const isCustomized = !isAutoName;
        if (isCustomized) {
            return;
        }

        const autoName = selectedModel.name;
        this.lastAutoCustomName = autoName;
        customNameControl.setValue(autoName, { emitEvent: false });
    }
}
