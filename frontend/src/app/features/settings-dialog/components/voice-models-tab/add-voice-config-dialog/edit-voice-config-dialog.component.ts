import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  FormBuilder,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { RealtimeModelConfigsService } from '../../../services/realtime-llms/real-time-model-config.service';
import { UpdateRealtimeModelConfigRequest } from '../../../models/realtime-voice/realtime-llm-config.model';
import { finalize } from 'rxjs/operators';
import { CustomInputComponent } from '../../../../../shared/components/form-input/form-input.component';
import { FullRealtimeConfig } from '../../../services/realtime-llms/full-reamtime-config.service';

@Component({
  selector: 'app-edit-voice-config-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    ButtonComponent,
    CustomInputComponent,
  ],
  templateUrl: './edit-voice-config-dialog.component.html',
  styleUrls: ['./edit-voice-config-dialog.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EditVoiceConfigDialogComponent implements OnInit {
  private dialogRef = inject(DialogRef);
  private formBuilder = inject(FormBuilder);
  private configService = inject(RealtimeModelConfigsService);
  private dialogData = inject<FullRealtimeConfig>(DIALOG_DATA);

  public form!: FormGroup;
  public isSubmitting = signal<boolean>(false);
  public errorMessage = signal<string | null>(null);
  public showApiKey = signal<boolean>(false);

  ngOnInit(): void {
    this.initForm();
  }

  private initForm(): void {
    this.form = this.formBuilder.group({
      customName: [this.dialogData.custom_name, Validators.required],
      apiKey: [this.dialogData.api_key, Validators.required],
    });
  }

  public toggleApiKeyVisibility(): void {
    this.showApiKey.set(!this.showApiKey());
  }

  public onSubmit(): void {
    if (this.form.invalid) {
      return;
    }

    this.isSubmitting.set(true);
    const formValue = this.form.value;

    const configData: UpdateRealtimeModelConfigRequest = {
      id: this.dialogData.id,
      realtime_model: this.dialogData.realtime_model,
      custom_name: formValue.customName,
      api_key: formValue.apiKey,
    };

    this.configService
      .updateConfig(configData)
      .pipe(finalize(() => this.isSubmitting.set(false)))
      .subscribe({
        next: () => {
          this.dialogRef.close(true); // Close with success result
        },
        error: (error) => {
          this.errorMessage.set(
            'Failed to update configuration. Please try again.'
          );
        },
      });
  }

  public onCancel(): void {
    this.dialogRef.close(false);
  }
}
