import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    OnInit,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { finalize } from 'rxjs/operators';
import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { HelpTooltipComponent } from '../../../../../shared/components/help-tooltip/help-tooltip.component';
import { JsonEditorComponent } from '../../../../../shared/components/json-editor/json-editor.component';
import { NumberStepperComponent } from '../../../../../shared/components/number-stepper/number-stepper.component';
import { SliderWithStepperComponent } from '../../../../../shared/components/slider-with-stepper/slider-with-stepper.component';
import { LLM_Provider, ModelTypes } from '../../../models/llm-provider.model';
import { LLM_Model } from '../../../models/llms/LLM.model';
import { CreateLLMConfigRequest, GetLlmConfigRequest } from '../../../models/llms/LLM_config.model';
import { LLM_Providers_Service } from '../../../services/llm-providers.service';
import { LLM_Config_Service } from '../../../services/llms/llm-config.service';
import { LLM_Models_Service } from '../../../services/llms/llm-models.service';
import { getProviderIconPath } from '../../../utils/get-provider-icon';
import {
    ModelSelectorModalComponent,
    ModelSelectorResult,
} from '../model-selector-modal/model-selector-modal.component';

const LLM_FORM_DEFAULTS = {
    temperature: 0.7,
    topP: 1,
    presencePenalty: 0,
    frequencyPenalty: 0,
    maxTokens: 4096,
    timeout: 30,
    seed: null as number | null,
};

export interface AddLlmConfigDialogData {
    editConfig?: GetLlmConfigRequest;
}

@Component({
    selector: 'app-add-llm-config-dialog',
    standalone: true,
    imports: [
        CommonModule,
        ReactiveFormsModule,
        ButtonComponent,
        SliderWithStepperComponent,
        NumberStepperComponent,
        JsonEditorComponent,
        AppSvgIconComponent,
        HelpTooltipComponent,
    ],
    templateUrl: './add-llm-config-dialog.component.html',
    styleUrls: ['./add-llm-config-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddLlmConfigDialogComponent implements OnInit {
    private dialogRef = inject(DialogRef);
    private dialog = inject(Dialog);
    private dialogData = inject<AddLlmConfigDialogData | null>(DIALOG_DATA, { optional: true });
    private providersService = inject(LLM_Providers_Service);
    private modelsService = inject(LLM_Models_Service);
    private configService = inject(LLM_Config_Service);
    private destroyRef = inject(DestroyRef);
    private cdr = inject(ChangeDetectorRef);
    private fb = inject(FormBuilder);

    form: FormGroup = this.fb.group({
        customName: ['', Validators.required],
        apiKey: ['', Validators.required],
        temperature: [LLM_FORM_DEFAULTS.temperature],
        topP: [LLM_FORM_DEFAULTS.topP, [Validators.min(0.1)]],
        presencePenalty: [LLM_FORM_DEFAULTS.presencePenalty],
        frequencyPenalty: [LLM_FORM_DEFAULTS.frequencyPenalty],
        maxTokens: [LLM_FORM_DEFAULTS.maxTokens, [Validators.required, Validators.min(500), Validators.max(128000)]],
        timeout: [LLM_FORM_DEFAULTS.timeout, [Validators.required, Validators.min(1), Validators.max(600)]],
        seed: [LLM_FORM_DEFAULTS.seed, [Validators.min(-2147483648), Validators.max(2147483647)]],
        headers: this.fb.array([this.createHeaderGroup()]),
    });

    isLoading = signal(false);
    isSubmitting = signal(false);
    errorMessage = signal<string | null>(null);
    showApiKey = signal(false);
    formValid = signal(false);

    providers = signal<LLM_Provider[]>([]);
    models = signal<LLM_Model[]>([]);

    selectedProvider = signal<LLM_Provider | null>(null);
    selectedModel = signal<LLM_Model | null>(null);
    selectedProviderId = signal<number | null>(null);
    selectedModelId = signal<number | null>(null);

    logitBiasText = signal('{}');
    headersText = signal('{}');
    headers = signal<Record<string, string>>({});
    private isUpdatingHeadersFromUI = false;

    logitBiasJson = computed(() => this.logitBiasText());

    headersJson = computed(() => this.headersText());

    isEditMode = computed(() => !!this.dialogData?.editConfig);

    dialogTitle = computed(() => (this.isEditMode() ? 'Edit LLM Configuration' : 'Add LLM Configuration'));

    submitButtonText = computed(() => {
        if (this.isSubmitting()) {
            return this.isEditMode() ? 'Saving...' : 'Adding...';
        }
        return this.isEditMode() ? 'Save' : 'Add LLM';
    });

    isFormValid = computed(() => {
        const valid = this.formValid();
        const hasProvider = this.selectedProviderId() !== null;
        const hasModel = this.selectedModelId() !== null;

        const finalResult = valid && hasProvider && hasModel;

        return finalResult;
    });

    getProviderIcon = getProviderIconPath;

    get headersArray(): FormArray {
        return this.form.get('headers') as FormArray;
    }

    constructor() {
        effect(() => {
            const provider = this.selectedProvider();
            const model = this.selectedModel();

            if (!this.isEditMode() && provider && model && !this.form.get('customName')?.value) {
                this.form.patchValue({ customName: `${provider.name}/${model.name}` });
            }
        });

        this.subscribeToHeadersChanges();

        this.form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.formValid.set(this.form.valid);
        });

        this.formValid.set(this.form.valid);
    }

    private createHeaderGroup(): FormGroup {
        return this.fb.group({
            key: [''],
            value: [''],
        });
    }

    ngOnInit(): void {
        this.loadProvidersAndEditConfig();

        this.dialogRef.keydownEvents
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(event => {
                if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                    event.preventDefault();
                    this.onSubmit();
                }
            });
    }

    openModelSelector(): void {
        const dialogRef = this.dialog.open(ModelSelectorModalComponent, {
            data: {
                selectedModelId: this.selectedModelId(),
            },
            disableClose: true,
        });

        dialogRef.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (result) {
                const { provider, model } = result as ModelSelectorResult;
                this.selectedProvider.set(provider);
                this.selectedModel.set(model);
                this.selectedProviderId.set(provider.id);
                this.selectedModelId.set(model.id);
            } else if (result === null) {
                this.selectedProvider.set(null);
                this.selectedModel.set(null);
                this.selectedProviderId.set(null);
                this.selectedModelId.set(null);
            }
        });
    }

    private populateFormFromConfig(config: GetLlmConfigRequest): void {
        const temperature = typeof config.temperature === 'number' ? config.temperature : LLM_FORM_DEFAULTS.temperature;
        const topP = typeof config.top_p === 'number' && config.top_p >= 0.1 ? config.top_p : LLM_FORM_DEFAULTS.topP;
        const presencePenalty =
            typeof config.presence_penalty === 'number' ? config.presence_penalty : LLM_FORM_DEFAULTS.presencePenalty;
        const frequencyPenalty =
            typeof config.frequency_penalty === 'number'
                ? config.frequency_penalty
                : LLM_FORM_DEFAULTS.frequencyPenalty;
        const maxTokens =
            typeof config.max_tokens === 'number' && config.max_tokens >= 500
                ? config.max_tokens
                : LLM_FORM_DEFAULTS.maxTokens;
        const timeout =
            typeof config.timeout === 'number' && config.timeout >= 1 ? config.timeout : LLM_FORM_DEFAULTS.timeout;
        const seed =
            typeof config.seed === 'number' && config.seed >= -2147483648 && config.seed <= 2147483647
                ? config.seed
                : LLM_FORM_DEFAULTS.seed;

        this.form.patchValue({
            customName: config.custom_name,
            apiKey: config.api_key,
            temperature,
            topP,
            presencePenalty,
            frequencyPenalty,
            maxTokens,
            timeout,
            seed,
        });

        this.selectedModelId.set(config.model);

        this.logitBiasText.set(JSON.stringify(config.logit_bias ?? {}, null, 2));

        const headersToSet = config.headers || {};
        this.isUpdatingHeadersFromUI = true;
        this.rebuildHeadersFormArray(headersToSet);
        this.headers.set(headersToSet);
        this.headersText.set(JSON.stringify(headersToSet, null, 2));
        this.cdr.detectChanges();

        setTimeout(() => {
            this.isUpdatingHeadersFromUI = false;
        }, 200);
    }

    private rebuildHeadersFormArray(headersObj: Record<string, string>): void {
        const entries = Object.entries(headersObj);
        const controls: FormGroup[] = entries.map(([key, value]) => this.fb.group({ key: [key], value: [value] }));

        controls.push(this.createHeaderGroup());

        const newArray = this.fb.array(controls);
        this.form.setControl('headers', newArray);

        this.subscribeToHeadersChanges();
    }

    private patchHeadersFormArray(headersObj: Record<string, string>): void {
        const entries = Object.entries(headersObj);
        const targetTotalRows = entries.length + 1;

        entries.forEach(([key, value], i) => {
            if (i < this.headersArray.length) {
                this.headersArray.at(i).patchValue({ key, value }, { emitEvent: false });
            } else {
                this.headersArray.push(this.fb.group({ key: [key], value: [value] }), { emitEvent: false });
            }
        });

        while (this.headersArray.length < targetTotalRows) {
            this.headersArray.push(this.createHeaderGroup(), { emitEvent: false });
        }

        while (this.headersArray.length > targetTotalRows) {
            this.headersArray.removeAt(this.headersArray.length - 1, { emitEvent: false });
        }

        this.headersArray.at(this.headersArray.length - 1).patchValue({ key: '', value: '' }, { emitEvent: false });
    }

    private subscribeToHeadersChanges(): void {
        this.headersArray.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            if (this.isUpdatingHeadersFromUI) {
                return;
            }
            this.syncHeadersToJson();
        });
    }

    private loadProvidersAndEditConfig(): void {
        this.isLoading.set(true);
        this.providersService
            .getProvidersByQuery(ModelTypes.LLM)
            .pipe(
                finalize(() => this.isLoading.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (providers) => {
                    this.providers.set(providers);

                    if (this.dialogData?.editConfig) {
                        this.populateFormFromConfig(this.dialogData.editConfig);
                        this.loadEditConfigModelAndProvider(this.dialogData.editConfig.model, providers);
                    }
                },
                error: (error) => {
                    console.error('Error loading providers:', error);
                    this.errorMessage.set('Failed to load providers. Please try again.');
                },
            });
    }

    private loadEditConfigModelAndProvider(modelId: number, providers: LLM_Provider[]): void {
        this.modelsService
            .getLLMModelById(modelId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (model) => {
                    const provider = providers.find((p) => p.id === model.llm_provider);
                    if (provider) {
                        this.selectedProvider.set(provider);
                        this.selectedProviderId.set(provider.id);
                    }
                    this.selectedModel.set(model);
                    this.selectedModelId.set(model.id);
                },
                error: (error) => {
                    console.error('Error loading model:', error);
                },
            });
    }

    toggleApiKeyVisibility(): void {
        this.showApiKey.update((v) => !v);
    }

    addHeaderEntry(): void {
        this.headersArray.push(this.createHeaderGroup());
    }

    removeHeaderEntry(index: number): void {
        this.headersArray.removeAt(index);

        if (this.headersArray.length === 0) {
            this.headersArray.push(this.createHeaderGroup());
        }
    }

    private syncHeadersToJson(): void {
        const headersObj: Record<string, string> = {};
        this.headersArray.controls.forEach((control) => {
            const key = control.get('key')?.value?.trim();
            const value = control.get('value')?.value;

            if (key) {
                headersObj[key] = value || '';
            }
        });

        this.headers.set(headersObj);
        this.headersText.set(JSON.stringify(headersObj, null, 2));
    }

    onLogitBiasChange(json: string): void {
        this.logitBiasText.set(json);
    }

    private parseJsonObject<T>(json: string): T | null {
        try {
            const parsed = JSON.parse(json || '{}');
            if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
                const hasKeys = Object.keys(parsed).length > 0;
                return hasKeys ? (parsed as T) : null;
            }
        } catch {}
        return null;
    }

    onHeadersChange(json: string): void {
        this.headersText.set(json);

        try {
            const parsed = JSON.parse(json || '{}');
            if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
                const normalized = Object.entries(parsed as Record<string, unknown>).reduce(
                    (acc, [key, value]) => {
                        acc[key] = typeof value === 'string' ? value : String(value ?? '');
                        return acc;
                    },
                    {} as Record<string, string>
                );

                this.headers.set(normalized);
                this.isUpdatingHeadersFromUI = true;
                this.patchHeadersFormArray(normalized);
                setTimeout(() => {
                    this.isUpdatingHeadersFromUI = false;
                }, 0);
            }
        } catch {}
    }

    onSubmit(): void {
        this.form.markAllAsTouched();
        if (!this.isFormValid()) return;

        this.isSubmitting.set(true);
        this.errorMessage.set(null);

        const formValue = this.form.value;

        const logitBias = this.parseJsonObject<Record<string, number>>(this.logitBiasText());
        const headersObj = this.parseJsonObject<Record<string, string>>(this.headersText()) ?? this.headers();
        const headers = Object.keys(headersObj).length > 0 ? headersObj : undefined;

        const seedValue =
            formValue.seed !== null && formValue.seed >= -2147483648 && formValue.seed <= 2147483647
                ? formValue.seed
                : null;

        const configData: CreateLLMConfigRequest = {
            model: this.selectedModelId()!,
            custom_name: formValue.customName,
            api_key: formValue.apiKey,
            temperature: formValue.temperature,
            top_p: formValue.topP,
            presence_penalty: formValue.presencePenalty,
            frequency_penalty: formValue.frequencyPenalty,
            max_tokens: formValue.maxTokens,
            timeout: formValue.timeout,
            seed: seedValue,
            stop: [],
            logit_bias: logitBias,
            is_visible: true,
            headers,
        };

        const request$ = this.isEditMode()
            ? this.configService.updateConfig({
                  ...configData,
                  id: this.dialogData!.editConfig!.id,
              })
            : this.configService.createConfig(configData);

        request$
            .pipe(
                finalize(() => this.isSubmitting.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.dialogRef.close(true);
                },
                error: (error) => {
                    console.error('Error saving config:', error);
                    this.errorMessage.set('Failed to save configuration. Please try again.');
                },
            });
    }

    onCancel(): void {
        this.dialogRef.close(false);
    }
}
