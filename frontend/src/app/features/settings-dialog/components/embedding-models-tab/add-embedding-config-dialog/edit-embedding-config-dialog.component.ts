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
import { EmbeddingConfigsService } from '../../../services/embeddings/embedding_configs.service';
import {
  EmbeddingConfig,
  GetEmbeddingConfigRequest,
} from '../../../models/embeddings/embedding-config.model';
import { finalize } from 'rxjs/operators';
import { CustomInputComponent } from '../../../../../shared/components/form-input/form-input.component';
import { FullEmbeddingConfig } from '../../../services/embeddings/full-embedding.service';

@Component({
  selector: 'app-edit-embedding-config-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    ButtonComponent,
    CustomInputComponent,
  ],
  templateUrl: './edit-embedding-config-dialog.component.html',
  styleUrls: ['./edit-embedding-config-dialog.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EditEmbeddingConfigDialogComponent implements OnInit {
  private dialogRef = inject(DialogRef);
  private formBuilder = inject(FormBuilder);
  private configService = inject(EmbeddingConfigsService);
  private dialogData = inject<FullEmbeddingConfig>(DIALOG_DATA);

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

    const configData: EmbeddingConfig = {
      id: this.dialogData.id,
      model: this.dialogData.model,
      custom_name: formValue.customName,
      api_key: formValue.apiKey,
      task_type: this.dialogData.task_type,
      is_visible: this.dialogData.is_visible,
    };

    this.configService
      .updateEmbeddingConfig(configData)
      .pipe(finalize(() => this.isSubmitting.set(false)))
      .subscribe({
        next: () => {
          this.dialogRef.close(true); // Close with success result
        },
        error: (error) => {
          console.error('Error updating embedding config:', error);
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
