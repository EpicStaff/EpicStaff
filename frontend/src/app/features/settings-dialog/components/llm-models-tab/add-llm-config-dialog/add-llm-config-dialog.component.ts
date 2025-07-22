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
import { LLM_Model } from '../../../models/llms/LLM.model';
import { LLM_Providers_Service } from '../../../services/LLM_providers.service';
import { LLM_Models_Service } from '../../../services/llms/LLM_models.service';
import { LLM_Config_Service } from '../../../services/llms/LLM_config.service';
import { CreateLLMConfigRequest } from '../../../models/llms/LLM_config.model';
import { finalize } from 'rxjs/operators';
import { Subject, takeUntil } from 'rxjs';
import { CustomInputComponent } from '../../../../../shared/components/form-input/form-input.component';

@Component({
  selector: 'app-add-edit-config-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    ButtonComponent,
    CustomInputComponent,
  ],
  templateUrl: './add-llm-config-dialog.component.html',
  styleUrls: ['./add-llm-config-dialog.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddLlmConfigDialogComponent implements OnInit, OnDestroy {
  private dialogRef = inject(DialogRef);
  private formBuilder = inject(FormBuilder);
  private providersService = inject(LLM_Providers_Service);
  private modelsService = inject(LLM_Models_Service);
  private configService = inject(LLM_Config_Service);
  private destroy$ = new Subject<void>();

  public form!: FormGroup;
  public providers = signal<LLM_Provider[]>([]);
  public models = signal<LLM_Model[]>([]);
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
    this.modelsService
      .getLLMModels(providerId)
      .pipe(finalize(() => this.isLoading.set(false)))
      .subscribe({
        next: (models) => {
          this.models.set(models);
          // If there are models, select the first one. If not, set modelId to null.
          if (models.length > 0) {
            this.form.get('modelId')?.setValue(models[0].id);
          } else {
            this.form.get('modelId')?.setValue(null);
          }
        },
        error: (error) => {
          console.error('Error loading models:', error);
          this.errorMessage.set(
            'Failed to load models for the selected provider. Please try again.'
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

    const configData: CreateLLMConfigRequest = {
      model: formValue.modelId,
      custom_name: formValue.customName,
      api_key: formValue.apiKey,
      temperature: 0.7, // Default value
      num_ctx: 4096, // Default value
      is_visible: true,
    };

    this.configService
      .createConfig(configData)
      .pipe(finalize(() => this.isSubmitting.set(false)))
      .subscribe({
        next: () => {
          this.dialogRef.close(true); // Close with success result
        },
        error: (error) => {
          console.error('Error creating LLM config:', error);
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
