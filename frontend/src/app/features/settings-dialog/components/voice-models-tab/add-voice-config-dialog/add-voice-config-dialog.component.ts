import { DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { finalize } from 'rxjs/operators';

import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { CustomInputComponent } from '../../../../../shared/components/form-input/form-input.component';
import { LLM_Provider, ModelTypes } from '../../../models/llm-provider.model';
import { CreateRealtimeModelConfigRequest } from '../../../models/realtime-voice/realtime-llm-config.model';
import { RealtimeModel } from '../../../models/realtime-voice/realtime-model.model';
import { LLM_Providers_Service } from '../../../services/llm-providers.service';
import { RealtimeModelConfigsService } from '../../../services/realtime-llms/real-time-model-config.service';
import { RealtimeModelsService } from '../../../services/realtime-llms/real-time-models.service';

@Component({
    selector: 'app-add-voice-config-dialog',
    standalone: true,
    imports: [CommonModule, ReactiveFormsModule, ButtonComponent, CustomInputComponent],
    templateUrl: './add-voice-config-dialog.component.html',
    styleUrls: ['./add-voice-config-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddVoiceConfigDialogComponent implements OnInit {
    private dialogRef = inject(DialogRef);
    private formBuilder = inject(FormBuilder);
    private providersService = inject(LLM_Providers_Service);
    private modelsService = inject(RealtimeModelsService);
    private configService = inject(RealtimeModelConfigsService);
    private destroyRef = inject(DestroyRef);

    public form!: FormGroup;
    public providers = signal<LLM_Provider[]>([]);
    public models = signal<RealtimeModel[]>([]);
    public isLoading = signal<boolean>(false);
    public isSubmitting = signal<boolean>(false);
    public errorMessage = signal<string | null>(null);
    private lastAutoCustomName: string | null = null;

    ngOnInit(): void {
        this.initForm();
        this.loadProviders();
        this.setupProviderIdSubscription();
        this.setupModelIdSubscription();

        this.dialogRef.keydownEvents
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(event => {
                if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                    event.preventDefault();
                    this.onSubmit();
                }
            });
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
        });
    }

    private loadProviders(): void {
        this.isLoading.set(true);
        this.providersService
            .getProvidersByQuery(ModelTypes.REALTIME)
            .pipe(finalize(() => this.isLoading.set(false)))
            .subscribe({
                next: (providers) => {
                    this.providers.set(providers);
                    if (providers.length > 0) {
                        this.form.get('providerId')?.setValue(providers[0].id);
                        this.updateCustomNameIfNeeded();
                    }
                },
                error: () => {
                    this.errorMessage.set('Failed to load providers. Please try again.');
                },
            });
    }

    private loadModels(providerId: number): void {
        this.isLoading.set(true);
        this.modelsService
            .getAllModels()
            .pipe(finalize(() => this.isLoading.set(false)))
            .subscribe({
                next: (models) => {
                    const filteredModels = models.filter((model) => model.provider === providerId);
                    this.models.set(filteredModels);
                    if (filteredModels.length > 0) {
                        this.form.get('modelId')?.setValue(filteredModels[0].id);
                        this.updateCustomNameIfNeeded();
                    } else {
                        this.form.get('modelId')?.setValue(null);
                    }
                },
                error: () => {
                    this.errorMessage.set('Failed to load models for the selected provider. Please try again.');
                },
            });
    }

    public onSubmit(): void {
        this.form.markAllAsTouched();
        if (this.form.invalid) {
            return;
        }
        this.isSubmitting.set(true);
        const formValue = this.form.value;
        const configData: CreateRealtimeModelConfigRequest = {
            realtime_model: formValue.modelId,
            custom_name: formValue.customName,
            api_key: formValue.apiKey,
        };
        this.configService
            .createConfig(configData)
            .pipe(finalize(() => this.isSubmitting.set(false)))
            .subscribe({
                next: () => {
                    this.dialogRef.close(true);
                },
                error: () => {
                    this.errorMessage.set('Failed to create configuration. Please try again.');
                },
            });
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
