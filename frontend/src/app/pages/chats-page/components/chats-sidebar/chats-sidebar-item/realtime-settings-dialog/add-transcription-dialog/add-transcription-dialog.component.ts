import { Component, DestroyRef, Inject, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import {
  FormBuilder,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { ToastService } from '../../../../../../../services/notifications/toast.service';
import { TranscriptionConfigsService } from '../../../../../../../services/transcription-config.service';
import {
  CreateTranscriptionConfigRequest,
  GetRealtimeTranscriptionModelRequest,
  GetTranscriptionConfigRequest,
} from '../../../../../../../shared/models/transcription-config.model';
import { ApiGetResponse, RealtimeTranscriptionModelsService } from '../../../../../../../services/transcription-models.service';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

export interface AddTranscriptionConfigDialogData {
  providerId?: number;
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
  ) { }

  ngOnInit(): void {
    this.loadModels();
    this.initForm();
    this.setupModelSubscription();
  }

  private initForm(): void {
    this.transcriptionForm = this.fb.group({
      realtime_transcription_model: [null, Validators.required],
      custom_name: ['', Validators.required],
      api_key: ['', Validators.required],
    });
  }

  private setupModelSubscription(): void {
    this.transcriptionForm
      .get('realtime_transcription_model')
      ?.valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.updateCustomName());
  }

  showError(controlName: string): boolean {
    const control = this.transcriptionForm.get(controlName);
    return control
      ? control.invalid && (control.touched || control.dirty)
      : false;
  }

  toggleApiKeyVisibility(): void {
    this.showApiKey = !this.showApiKey;
  }

  loadModels(): void {
    this.realtimeTranscriptionModelsService.getAllModels()
      .subscribe((res: ApiGetResponse<GetRealtimeTranscriptionModelRequest>) => {
        this.models = res.results;
        this.updateCustomName();
      })
  }

  onConfirm(): void {
    if (this.transcriptionForm.valid) {
      this.submitting = true;
      const formValue = this.transcriptionForm.value;

      const config: CreateTranscriptionConfigRequest = {
        realtime_transcription_model: formValue.realtime_transcription_model,
        api_key: formValue.api_key,
        custom_name: formValue.custom_name,
      };

      // Create the transcription config through the service
      this.transcriptionConfigsService
        .createTranscriptionConfig(config)
        .subscribe({
          next: (createdConfig: GetTranscriptionConfigRequest) => {
            this.toastService.success(
              `Transcription configuration "${createdConfig.custom_name}" has been successfully created`
            );
            // Close the dialog with the created config
            this.dialogRef.close(createdConfig);
            this.submitting = false;
          },
          error: (error) => {
            console.error('Error creating transcription config:', error);
            this.toastService.error(
              'Failed to create transcription configuration'
            );
            this.submitting = false;
          },
        });
    } else {
      // Mark all fields as touched to show validation errors
      this.transcriptionForm.markAllAsTouched();
    }
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

    const autoName = selectedModel.name;
    this.lastAutoCustomName = autoName;
    customNameControl.setValue(autoName, { emitEvent: false });
  }
}
