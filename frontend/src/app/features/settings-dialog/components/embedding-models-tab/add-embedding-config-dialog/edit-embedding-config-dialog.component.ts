import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
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
import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { EmbeddingConfigsService } from '../../../services/embeddings/embedding_configs.service';
import { EmbeddingConfig } from '../../../models/embeddings/embedding-config.model';
import { finalize } from 'rxjs/operators';
import { FullEmbeddingConfig } from '../../../services/embeddings/full-embedding.service';
import { AppIconComponent } from '../../../../../shared/components/app-icon/app-icon.component';
import { LLM_Provider } from '../../../models/LLM_provider.model';
import { EmbeddingModel } from '../../../models/embeddings/embedding.model';
import {
  ModelSelectorModalComponent,
  ModelSelectorResult,
} from '../model-selector-modal/model-selector-modal.component';
import { getProviderIconPath } from '../../../utils/get-provider-icon';

@Component({
  selector: 'app-edit-embedding-config-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    ButtonComponent,
    AppIconComponent,
  ],
  templateUrl: './edit-embedding-config-dialog.component.html',
  styleUrls: ['./edit-embedding-config-dialog.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EditEmbeddingConfigDialogComponent implements OnInit {
  private readonly dialogRef = inject(DialogRef);
  private readonly dialog = inject(Dialog);
  private readonly formBuilder = inject(FormBuilder);
  private readonly configService = inject(EmbeddingConfigsService);
  private readonly dialogData = inject<FullEmbeddingConfig>(DIALOG_DATA);

  public form!: FormGroup;
  public readonly selectedProvider = signal<LLM_Provider | null>(null);
  public readonly selectedModel = signal<EmbeddingModel | null>(null);
  public readonly selectedModelId = signal<number | null>(null);
  public isSubmitting = signal<boolean>(false);
  public errorMessage = signal<string | null>(null);
  public showApiKey = signal<boolean>(false);
  public readonly getProviderIcon = getProviderIconPath;
  public readonly isFormValid = computed(
    () =>
      this.form.valid &&
      this.selectedModelId() !== null
  );

  public ngOnInit(): void {
    this.initForm();
    this.selectedProvider.set(this.dialogData.providerDetails ?? null);
    this.selectedModel.set(this.dialogData.modelDetails ?? null);
    this.selectedModelId.set(this.dialogData.model ?? null);
  }

  private initForm(): void {
    this.form = this.formBuilder.group({
      modelId: [this.dialogData.model, Validators.required],
      customName: [this.dialogData.custom_name, Validators.required],
      apiKey: [this.dialogData.api_key, Validators.required],
    });
  }

  public toggleApiKeyVisibility(): void {
    this.showApiKey.set(!this.showApiKey());
  }

  public onSubmit(): void {
    if (!this.isFormValid()) {
      return;
    }

    this.isSubmitting.set(true);
    const formValue = this.form.getRawValue();
    const modelId = this.selectedModelId();
    if (!modelId) {
      this.isSubmitting.set(false);
      return;
    }

    const configData: EmbeddingConfig = {
      id: this.dialogData.id,
      model: modelId,
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

  public openModelSelector(): void {
    const ref = this.dialog.open(ModelSelectorModalComponent, {
      data: {
        selectedModelId: this.selectedModelId(),
      },
      disableClose: true,
    });

    ref.closed.subscribe((result) => {
      if (result === null) {
        this.selectedProvider.set(null);
        this.selectedModel.set(null);
        this.selectedModelId.set(null);
        this.form.patchValue({ modelId: null });
        return;
      }

      if (!result) {
        return;
      }

      const selected = result as ModelSelectorResult;
      this.selectedProvider.set(selected.provider);
      this.selectedModel.set(selected.model);
      this.selectedModelId.set(selected.model.id);
      this.form.patchValue({ modelId: selected.model.id });
    });
  }
}
