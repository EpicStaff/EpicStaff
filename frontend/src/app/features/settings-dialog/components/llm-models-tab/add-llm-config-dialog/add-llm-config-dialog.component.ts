import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    OnInit,
    inject,
    signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
    FormBuilder,
    FormGroup,
    FormControl,
    ReactiveFormsModule,
    Validators,
} from '@angular/forms';
import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { LLM_Provider, ModelTypes } from '../../../models/LLM_provider.model';
import { LLM_Model } from '../../../models/llms/LLM.model';
import { LLM_Providers_Service } from '../../../services/LLM_providers.service';
import { LLM_Models_Service } from '../../../services/llms/LLM_models.service';
import { LLM_Config_Service } from '../../../services/llms/LLM_config.service';
import { CreateLLMConfigRequest } from '../../../models/llms/LLM_config.model';
import { finalize } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CustomInputComponent } from '../../../../../shared/components/form-input/form-input.component';
import { MatSliderModule } from '@angular/material/slider';

@Component({
    selector: 'app-add-edit-config-dialog',
    standalone: true,
    imports: [
        CommonModule,
        ReactiveFormsModule,
        ButtonComponent,
        CustomInputComponent,
        MatSliderModule,
    ],
    templateUrl: './add-llm-config-dialog.component.html',
    styleUrls: ['./add-llm-config-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddLlmConfigDialogComponent implements OnInit {
    private dialogRef = inject(DialogRef);
    private formBuilder = inject(FormBuilder);
    private providersService = inject(LLM_Providers_Service);
    private modelsService = inject(LLM_Models_Service);
    private configService = inject(LLM_Config_Service);
    private destroyRef = inject(DestroyRef);

    public form!: FormGroup;
    public providers = signal<LLM_Provider[]>([]);
    public models = signal<LLM_Model[]>([]);
    public isLoading = signal<boolean>(false);
    public isSubmitting = signal<boolean>(false);
    public errorMessage = signal<string | null>(null);
    private lastAutoCustomName: string | null = null;

    get temperatureControl(): FormControl {
        return this.form.get('temperature') as FormControl;
    }

    ngOnInit(): void {
        this.initForm();
        this.loadProviders();
        this.setupProviderIdSubscription();
        this.setupModelIdSubscription();
    }

    private setupProviderIdSubscription(): void {
        this.form
            .get('providerId')
            ?.valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((providerId) => {
                if (providerId) {
                    this.loadModels(providerId);
                } else {
                    this.models.set([]);
                    this.form.get('modelId')?.setValue(null);
                }

                this.updateCustomNameIfNeeded();
            });
    }

    private setupModelIdSubscription(): void {
        this.form
            .get('modelId')
            ?.valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.updateCustomNameIfNeeded());
    }

    private initForm(): void {
        this.form = this.formBuilder.group({
            providerId: [null, Validators.required],
            modelId: [null, Validators.required],
            customName: ['', Validators.required],
            apiKey: ['', Validators.required],
            temperature: [0, [Validators.min(0), Validators.max(100)]], // 0-100 range, default 70 (0.7)
        });
    }

    private loadProviders(): void {
        this.isLoading.set(true);
        this.providersService
            .getProvidersByQuery(ModelTypes.LLM)
            .pipe(finalize(() => this.isLoading.set(false)))
            .subscribe({
                next: (providers) => {
                    this.providers.set(providers);
                    if (providers.length > 0) {
                        this.form.get('providerId')?.setValue(providers[0].id);
                        this.updateCustomNameIfNeeded();
                    }
                },
                error: (error) => {
                    console.error('Error loading providers:', error);
                    this.errorMessage.set(
                        'Failed to load providers. Please try again.'
                    );
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
                    if (models.length > 0) {
                        this.form.get('modelId')?.setValue(models[0].id);
                        this.updateCustomNameIfNeeded();
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
            temperature: formValue.temperature / 100,
            num_ctx: 4096,
            is_visible: true,
        };

        this.configService
            .createConfig(configData)
            .pipe(finalize(() => this.isSubmitting.set(false)))
            .subscribe({
                next: () => {
                    this.dialogRef.close(true);
                },
                error: (error) => {
                    console.error('Error creating LLM config:', error);
                    this.errorMessage.set(
                        'Failed to create configuration. Please try again.'
                    );
                },
            });
    }

    public onTemperatureChange(event: Event): void {
        const newValue = (event.target as HTMLInputElement).value || 0;
        this.temperatureControl.setValue(Number(newValue));
    }

    public onCancel(): void {
        this.dialogRef.close(false);
    }

    private updateCustomNameIfNeeded(): void {
        const providerId = this.form.get('providerId')?.value;
        const modelId = this.form.get('modelId')?.value;
        if (!providerId || !modelId) {
            return;
        }

        const provider = this.providers().find((p) => p.id === providerId);
        const model = this.models().find((m) => m.id === modelId);
        if (!provider || !model) {
            return;
        }

        const autoName = `${provider.name}/${model.name}`;
        const customNameControl = this.form.get('customName');
        if (!customNameControl) {
            return;
        }

        this.lastAutoCustomName = autoName;
        customNameControl.setValue(autoName, { emitEvent: false });
    }
}
