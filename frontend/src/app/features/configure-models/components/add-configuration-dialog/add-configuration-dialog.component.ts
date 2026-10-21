import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    OnInit,
    signal,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    HelpTooltipComponent,
    HintMessageComponent,
    IconButtonComponent,
    InputNumberComponent,
    JsonEditorFormFieldComponent,
    KeyValueListComponent,
    LlmReasoningEffortFieldComponent,
    SelectComponent,
    SelectItem,
    SliderWithStepperComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { DEFAULT_STEP_SIZE, TOKEN_PRICE_HINT } from '@shared/constants';
import { EnterSubmitDirective } from '@shared/directives';
import { pricePairValidator } from '@shared/form-validators';
import { CreateEmbeddingConfigRequest, ModelTypes, ReasoningEffort } from '@shared/models';
import { EmbeddingConfigStorageService, LlmConfigStorageService, SecretsStorageService } from '@shared/services';
import { extractFieldErrorMessages, extractHttpErrorMessage, perMillionToPerToken } from '@shared/utils';
import { catchError, EMPTY, map, merge, Observable, startWith, tap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { LlmModelSelectorComponent } from '../../../../shared/components/llm-dialogs/llm-model-selector/llm-model-selector.component';
import { ElevenLabsRealtimeConfigStorageService } from '../../services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../services/llms/openai-realtime-config-storage.service';
import { RealtimeProvider } from '../realtime-config-dialog/realtime-config-dialog.component';

export type ConfigTab = 'llm' | 'realtime' | 'embedding';

const DUPLICATE_EMBEDDING_NAME_MESSAGE =
    'An embedding configuration with this name already exists. Please choose a different name.';

@Component({
    selector: 'app-add-configuration-dialog',
    templateUrl: './add-configuration-dialog.component.html',
    styleUrls: ['./add-configuration-dialog.component.scss'],
    imports: [
        ReactiveFormsModule,
        IconButtonComponent,
        HelpTooltipComponent,
        ButtonComponent,
        CustomInputComponent,
        SelectComponent,
        HintMessageComponent,
        ValidationErrorsComponent,
        KeyValueListComponent,
        SliderWithStepperComponent,
        InputNumberComponent,
        JsonEditorFormFieldComponent,
        LlmModelSelectorComponent,
        LlmReasoningEffortFieldComponent,
        EnterSubmitDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddConfigurationDialogComponent implements OnInit {
    private readonly reasoningEffortField = viewChild(LlmReasoningEffortFieldComponent);

    private readonly fb = inject(FormBuilder);
    private readonly destroyRef = inject(DestroyRef);
    private readonly llmStorage = inject(LlmConfigStorageService);
    private readonly openaiStorage = inject(OpenAIRealtimeConfigStorageService);
    private readonly elevenLabsStorage = inject(ElevenLabsRealtimeConfigStorageService);
    private readonly geminiStorage = inject(GeminiRealtimeConfigStorageService);
    private readonly embeddingConfigStorage = inject(EmbeddingConfigStorageService);
    private readonly toast = inject(ToastService);
    private readonly secretsStorageService = inject(SecretsStorageService);
    readonly dialogRef = inject(DialogRef);
    readonly data = inject<{ initialTab?: ConfigTab }>(DIALOG_DATA, { optional: true });
    protected readonly DEFAULT_STEP_SIZE = DEFAULT_STEP_SIZE;
    protected readonly TOKEN_PRICE_HINT = TOKEN_PRICE_HINT;

    activeTab = signal<ConfigTab>(this.data?.initialTab ?? 'llm');
    selectedProvider = signal<RealtimeProvider>('openai');
    isSubmitting = signal(false);
    errorMessage = signal<string | null>(null);
    // Saving before the LLM model is known would send reasoning_effort as null instead of the chosen value.
    readonly isLlmModelResolving = computed(
        () => this.activeTab() === 'llm' && (this.reasoningEffortField()?.resolving() ?? false)
    );
    readonly submitLabel = computed(() => {
        switch (this.activeTab()) {
            case 'llm':
                return 'Add LLM';
            case 'realtime':
                return 'Create Realtime';
            case 'embedding':
                return 'Add Embedding';
        }
    });

    readonly realtimeProviders: { key: RealtimeProvider; label: string }[] = [
        { key: 'openai', label: 'OpenAI' },
        { key: 'elevenlabs', label: 'ElevenLabs' },
        { key: 'gemini', label: 'Gemini' },
    ];

    protected readonly llmModelControl = new FormControl<number | null>(null, [Validators.required]);
    protected readonly selectedLlmModelId = toSignal(this.llmModelControl.valueChanges, {
        initialValue: this.llmModelControl.value,
    });
    protected readonly reasoningEffortControl = new FormControl<ReasoningEffort | null>(null);
    llmForm!: FormGroup;

    private readonly pricingGroup = this.fb.group(
        {
            input_price_per_million: [null as number | null, [Validators.min(0)]],
            output_price_per_million: [null as number | null, [Validators.min(0)]],
        },
        { validators: pricePairValidator('input_price_per_million', 'output_price_per_million') }
    );
    private readonly isPricePairIncomplete = toSignal(
        merge(this.pricingGroup.statusChanges, this.pricingGroup.valueChanges).pipe(
            startWith(null),
            map(() => this.pricingGroup.hasError('pricePair'))
        ),
        { requireSync: true }
    );

    private readonly isLlmHeadersInvalid = signal(false);
    private readonly isEmbeddingHeadersInvalid = signal(false);

    readonly hasInvalidHeaders = computed(() => {
        switch (this.activeTab()) {
            case 'llm':
                return this.isLlmHeadersInvalid();
            case 'embedding':
                return this.isEmbeddingHeadersInvalid();
            default:
                return false;
        }
    });

    readonly hasIncompletePricePair = computed(() => this.activeTab() === 'llm' && this.isPricePairIncomplete());

    openaiForm = this.fb.nonNullable.group({
        custom_name: ['', Validators.required],
        api_key_secret_id: [null as number | null],
        model_name: ['gpt-realtime-1.5', Validators.required],
        transcription_model_name: ['whisper-1'],
        transcription_api_key_secret_id: [null as number | null],
        voice_recognition_prompt: [''],
    });

    elevenLabsForm = this.fb.nonNullable.group({
        custom_name: ['', Validators.required],
        api_key_secret_id: [null as number | null],
        model_name: ['eleven_turbo_v2_5', Validators.required],
        language: [''],
    });

    geminiForm = this.fb.nonNullable.group({
        custom_name: ['', Validators.required],
        api_key_secret_id: [null as number | null],
        model_name: ['gemini-3.1-flash-live-preview', Validators.required],
        voice_recognition_prompt: [''],
    });

    embeddingForm = this.fb.nonNullable.group({
        model: [null as number | null, Validators.required],
        api_key_secret_id: [null as number | null, Validators.required],
        custom_name: ['', Validators.required],
        extra_headers: this.fb.nonNullable.control<Record<string, string>>({}),
    });

    protected readonly ModelTypes = ModelTypes;

    secretItems = computed<SelectItem[]>(() =>
        this.secretsStorageService.secrets().map((secret) => ({
            name: secret.name,
            value: secret.id,
            tip: this.secretsStorageService.maskTail(secret.tail),
        }))
    );

    ngOnInit(): void {
        this.secretsStorageService
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ error: () => {} });

        this.llmForm = this.fb.group({
            custom_name: ['', [Validators.required]],
            api_key_secret_id: [null as number | null],
            model: this.llmModelControl,
            temperature: [0.5, [Validators.min(0), Validators.max(1)]],
            top_p: [1, [Validators.min(0.1)]],
            stop: [null],
            max_tokens: [4096, [Validators.min(500), Validators.max(2147483647)]],
            presence_penalty: [0],
            frequency_penalty: [0],
            logit_bias: [null],
            response_format: [null],
            seed: [null, [Validators.min(-2147483648), Validators.max(2147483647)]],
            extra_headers: [{}],
            timeout: [120, [Validators.min(1), Validators.max(600)]],
            reasoning_effort: this.reasoningEffortControl,
            is_visible: [true],
            pricing: this.pricingGroup,
        });

        this.llmForm
            .get('extra_headers')
            ?.statusChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((status) => this.isLlmHeadersInvalid.set(status === 'INVALID'));
        this.embeddingForm.controls.extra_headers.statusChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((status) => this.isEmbeddingHeadersInvalid.set(status === 'INVALID'));

        this.pricingGroup.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            if (this.pricingGroup.dirty) this.pricingGroup.markAsTouched();
        });

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.code === 'KeyS') {
                e.preventDefault();
                this.onSubmit();
            }
        });
    }

    selectProvider(provider: RealtimeProvider): void {
        this.selectedProvider.set(provider);
        this.errorMessage.set(null);
    }

    setActiveTab(tab: ConfigTab): void {
        this.activeTab.set(tab);
        this.errorMessage.set(null);
    }

    onSubmit(): void {
        switch (this.activeTab()) {
            case 'llm':
                this.submitLlm();
                break;
            case 'realtime':
                this.submitRealtime();
                break;
            case 'embedding':
                this.submitEmbedding();
                break;
        }
    }

    private submitLlm(): void {
        if (this.llmForm.invalid || this.isSubmitting() || this.isLlmModelResolving()) {
            this.llmForm.markAllAsTouched();
            return;
        }
        const { pricing, ...config } = this.llmForm.value;
        this.isSubmitting.set(true);
        this.llmStorage
            .createConfig({
                ...config,
                reasoning_effort: this.reasoningEffortField()?.submittedValue() ?? null,
                input_cost_per_token: perMillionToPerToken(pricing.input_price_per_million),
                output_cost_per_token: perMillionToPerToken(pricing.output_price_per_million),
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.isSubmitting.set(false);
                    this.toast.success('LLM configuration created successfully.');
                    this.dialogRef.close(true);
                },
                error: (error: HttpErrorResponse) => {
                    this.isSubmitting.set(false);
                    const reasoningEffortErrors = extractFieldErrorMessages(error, 'reasoning_effort');
                    if (
                        reasoningEffortErrors.length &&
                        this.reasoningEffortField()?.showServerErrors(reasoningEffortErrors)
                    ) {
                        return;
                    }
                    this.toast.error(extractHttpErrorMessage(error, 'Failed to create LLM configuration.'));
                },
            });
    }

    private submitRealtime(): void {
        const provider = this.selectedProvider();
        const activeForm =
            provider === 'openai' ? this.openaiForm : provider === 'elevenlabs' ? this.elevenLabsForm : this.geminiForm;

        if (activeForm.invalid) {
            activeForm.markAllAsTouched();
            return;
        }

        this.isSubmitting.set(true);
        const v = activeForm.getRawValue();

        let obs: Observable<unknown>;
        if (provider === 'openai') {
            obs = this.openaiStorage.createConfig(v);
        } else if (provider === 'elevenlabs') {
            obs = this.elevenLabsStorage.createConfig(v);
        } else {
            obs = this.geminiStorage.createConfig(v);
        }

        obs.pipe(
            tap(() => this.dialogRef.close(true)),
            catchError(() => {
                this.errorMessage.set('Failed to save configuration.');
                this.isSubmitting.set(false);
                return EMPTY;
            }),
            takeUntilDestroyed(this.destroyRef)
        ).subscribe();
    }

    private submitEmbedding(): void {
        const { model, api_key_secret_id, custom_name, extra_headers } = this.embeddingForm.getRawValue();
        if (this.embeddingForm.invalid || model === null || this.isSubmitting()) {
            this.embeddingForm.markAllAsTouched();
            return;
        }

        const trimmedName = custom_name.trim();
        const normalizedName = trimmedName.toLowerCase();
        const isDuplicate = this.embeddingConfigStorage
            .configs()
            .some((config) => config.custom_name.toLowerCase() === normalizedName);
        if (isDuplicate) {
            this.toast.error(DUPLICATE_EMBEDDING_NAME_MESSAGE);
            return;
        }

        const request: CreateEmbeddingConfigRequest = {
            model,
            api_key_secret_id,
            custom_name: trimmedName,
            extra_headers,
        };
        this.isSubmitting.set(true);
        this.embeddingConfigStorage
            .createConfig(request)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.isSubmitting.set(false);
                    this.toast.success('Embedding configuration created successfully.');
                    this.dialogRef.close(true);
                },
                error: (error: HttpErrorResponse) => {
                    this.isSubmitting.set(false);
                    this.toast.error(this.parseEmbeddingError(error));
                },
            });
    }

    private parseEmbeddingError(error: HttpErrorResponse): string {
        const nameError = error?.error?.custom_name?.[0] as string | undefined;
        if (nameError?.toLowerCase().includes('already exists')) {
            return DUPLICATE_EMBEDDING_NAME_MESSAGE;
        }
        return 'Failed to create embedding configuration.';
    }

    onCancel(): void {
        this.dialogRef.close(null);
    }
}
