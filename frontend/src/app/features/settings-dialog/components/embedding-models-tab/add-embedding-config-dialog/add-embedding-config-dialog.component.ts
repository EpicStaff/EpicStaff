import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
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
import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { LLM_Provider } from '../../../models/LLM_provider.model';
import { EmbeddingConfigsService } from '../../../services/embeddings/embedding_configs.service';
import { CreateEmbeddingConfigRequest } from '../../../models/embeddings/embedding-config.model';
import { finalize } from 'rxjs/operators';
import { EmbeddingModel } from '../../../models/embeddings/embedding.model';
import { AppIconComponent } from '../../../../../shared/components/app-icon/app-icon.component';
import {
  ModelSelectorModalComponent,
  ModelSelectorResult,
} from '../model-selector-modal/model-selector-modal.component';
import { getProviderIconPath } from '../../../utils/get-provider-icon';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

@Component({
  selector: 'app-add-embedding-config-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    ButtonComponent,
    AppIconComponent,
  ],
  templateUrl: './add-embedding-config-dialog.component.html',
  styleUrls: ['./add-embedding-config-dialog.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddEmbeddingConfigDialogComponent implements OnInit {
  private readonly dialogRef = inject(DialogRef);
  private readonly dialog = inject(Dialog);
  private readonly formBuilder = inject(FormBuilder);
  private readonly configService = inject(EmbeddingConfigsService);
  private readonly destroyRef = inject(DestroyRef);

  public form!: FormGroup;
  public readonly selectedProvider = signal<LLM_Provider | null>(null);
  public readonly selectedModel = signal<EmbeddingModel | null>(null);
  public readonly selectedModelId = signal<number | null>(null);
  public readonly formValid = signal(false);
  public readonly showApiKey = signal(false);
  public readonly submitAttempted = signal(false);
  public isSubmitting = signal<boolean>(false);
  public errorMessage = signal<string | null>(null);
  public readonly isFormValid = computed(
    () =>
      this.formValid() &&
      this.selectedProvider() !== null &&
      this.selectedModel() !== null &&
      this.selectedModelId() !== null
  );

  public readonly getProviderIcon = getProviderIconPath;

  public ngOnInit(): void {
    this.initForm();
    this.formValid.set(this.form.valid);
    this.form.statusChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      this.formValid.set(this.form.valid);
    });
  }

  private initForm(): void {
    this.form = this.formBuilder.group({
      modelId: [null, Validators.required],
      customName: ['', Validators.required],
      apiKey: ['', Validators.required],
    });
  }

  public onSubmit(): void {
    this.submitAttempted.set(true);
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

    const configData: CreateEmbeddingConfigRequest = {
      model: modelId,
      custom_name: formValue.customName,
      api_key: formValue.apiKey,
      task_type: 'retrieval_document',
      is_visible: true,
    };

    this.configService
      .createEmbeddingConfig(configData)
      .pipe(finalize(() => this.isSubmitting.set(false)))
      .subscribe({
        next: () => {
          this.dialogRef.close(true);
        },
        error: () => {
          this.errorMessage.set(
            'Failed to create configuration. Please try again.'
          );
        },
      });
  }

  public onCancel(): void {
    this.dialogRef.close(false);
  }

  public toggleApiKeyVisibility(): void {
    this.showApiKey.set(!this.showApiKey());
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
      this.updateCustomNameIfNeeded();
    });
  }

  private updateCustomNameIfNeeded(): void {
    const provider = this.selectedProvider();
    const model = this.selectedModel();
    if (!provider || !model) {
      return;
    }

    const customNameControl = this.form.get('customName');
    if (!customNameControl) {
      return;
    }

    customNameControl.setValue(`${provider.name}/${model.name}`, { emitEvent: false });
  }
}
