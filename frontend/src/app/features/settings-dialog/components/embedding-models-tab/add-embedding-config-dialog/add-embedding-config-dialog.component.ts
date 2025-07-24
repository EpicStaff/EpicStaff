import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
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
import { LLM_Provider } from '../../../models/LLM_provider.model';
import { LLM_Providers_Service } from '../../../services/LLM_providers.service';
import { EmbeddingModelsService } from '../../../services/embeddings/embeddings.service';
import { EmbeddingConfigsService } from '../../../services/embeddings/embedding_configs.service';
import { CreateEmbeddingConfigRequest } from '../../../models/embeddings/embedding-config.model';
import { finalize } from 'rxjs/operators';
import { Subject, takeUntil } from 'rxjs';
import { CustomInputComponent } from '../../../../../shared/components/form-input/form-input.component';
import { EmbeddingModel } from '../../../models/embeddings/embedding.model';

@Component({
  selector: 'app-add-embedding-config-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    ButtonComponent,
    CustomInputComponent,
  ],
  templateUrl: './add-embedding-config-dialog.component.html',
  styleUrls: ['./add-embedding-config-dialog.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddEmbeddingConfigDialogComponent implements OnInit, OnDestroy {
  private dialogRef = inject(DialogRef);
  private formBuilder = inject(FormBuilder);
  private providersService = inject(LLM_Providers_Service);
  private embeddingModelsService = inject(EmbeddingModelsService);
  private configService = inject(EmbeddingConfigsService);
  private destroy$ = new Subject<void>();

  public form!: FormGroup;
  public providers = signal<LLM_Provider[]>([]);
  public models = signal<EmbeddingModel[]>([]);
  public isLoading = signal<boolean>(false);
  public isSubmitting = signal<boolean>(false);
  public errorMessage = signal<string | null>(null);

  ngOnInit(): void {
    this.initForm();
    this.loadProviders();

    // Listen to provider changes to load models
    this.form
      .get('providerId')
      ?.valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe((providerId) => {
        if (providerId) {
          this.loadModels(providerId);
        } else {
          this.models.set([]);
          this.form.get('modelId')?.setValue(null);
        }
      });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  private initForm(): void {
    this.form = this.formBuilder.group({
      providerId: [null, Validators.required],
      modelId: [null, Validators.required],
      customName: ['', Validators.required],
      apiKey: ['', Validators.required],
    });
  }

  private loadProviders(): void {
    this.isLoading.set(true);
    this.providersService
      .getProviders()
      .pipe(finalize(() => this.isLoading.set(false)))
      .subscribe({
        next: (providers) => {
          this.providers.set(providers);
          // Automatically select the first provider if available
          if (providers.length > 0) {
            this.form.get('providerId')?.setValue(providers[0].id);
          }
        },
        error: (error) => {
          console.error('Error loading providers:', error);
          this.errorMessage.set('Failed to load providers. Please try again.');
        },
      });
  }

  private loadModels(providerId: number): void {
    this.isLoading.set(true);
    this.embeddingModelsService
      .getEmbeddingModels(providerId)
      .pipe(finalize(() => this.isLoading.set(false)))
      .subscribe({
        next: (models) => {
          this.models.set(models);

          if (models.length > 0) {
            this.form.get('modelId')?.setValue(models[0].id);
          } else {
            this.form.get('modelId')?.setValue(null);
          }
        },
        error: (error) => {
          console.error('Error loading models:', error);
          this.errorMessage.set(
            'Failed to load embedding models for the selected provider. Please try again.'
          );
        },
      });
  }

  public onSubmit(): void {
    if (this.form.invalid) {
      return;
    }

    this.isSubmitting.set(true);
    const formValue = this.form.value;

    const configData: CreateEmbeddingConfigRequest = {
      model: formValue.modelId,
      custom_name: formValue.customName,
      api_key: formValue.apiKey,
      task_type: 'retrieval_document', // Default value
      is_visible: true,
    };

    this.configService
      .createEmbeddingConfig(configData)
      .pipe(finalize(() => this.isSubmitting.set(false)))
      .subscribe({
        next: () => {
          this.dialogRef.close(true); // Close with success result
        },
        error: (error) => {
          console.error('Error creating embedding config:', error);
          this.errorMessage.set(
            'Failed to create configuration. Please try again.'
          );
        },
      });
  }

  public onCancel(): void {
    this.dialogRef.close(false);
  }
}
