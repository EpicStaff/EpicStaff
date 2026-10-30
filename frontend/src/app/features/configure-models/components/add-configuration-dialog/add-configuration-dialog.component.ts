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
import { MatTooltip } from '@angular/material/tooltip';
import {
    ButtonComponent,
    CustomInputComponent,
    ErrorBannerComponent,
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
import { extractFieldErrorMessages, extractHttpErrorMessage, isClientError, perMillionToPerToken } from '@shared/utils';
import { map, merge, startWith } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { LlmModelSelectorComponent } from '../../../../shared/components/llm-dialogs/llm-model-selector/llm-model-selector.component';
import { RealtimeConfigFormComponent } from '../realtime-config-form/realtime-config-form.component';

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
        ButtonComponent,
        CustomInputComponent,
        ErrorBannerComponent,
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
        MatTooltip,
        RealtimeConfigFormComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddConfigurationDialogComponent implements OnInit {
    private readonly reasoningEffortField = viewChild(LlmReasoningEffortFieldComponent);
    private readonly realtimeForm = viewChild(RealtimeConfigFormComponent);

    private readonly fb = inject(FormBuilder);
    private readonly destroyRef = inject(DestroyRef);
    private readonly llmStorage = inject(LlmConfigStorageService);
    private readonly embeddingConfigStorage = inject(EmbeddingConfigStorageService);
    private readonly toast = inject(ToastService);
    private readonly secretsStorageService = inject(SecretsStorageService);
    readonly dialogRef = inject(DialogRef);
    readonly data = inject<{ initialTab?: ConfigTab }>(DIALOG_DATA, { optional: true });
    protected readonly DEFAULT_STEP_SIZE = DEFAULT_STEP_SIZE;
    protected readonly TOKEN_PRICE_HINT = TOKEN_PRICE_HINT;

    activeTab = signal<ConfigTab>(this.data?.initialTab ?? 'llm');
    isSubmitting = signal(false);
    /** The server's refusal of the last LLM or embedding save; the realtime form keeps its own. */
    errorMessage = signal<string | null>(null);
    // The realtime tab's form saves itself; its progress counts as this dialog's.
    protected readonly isSaving = computed(() => this.isSubmitting() || (this.realtimeForm()?.isSubmitting() ?? false));
    // One banner for the dialog, showing the active tab's error.
    protected readonly bannerMessage = computed(() =>
        this.activeTab() === 'realtime' ? (this.realtimeForm()?.errorMessage() ?? null) : this.errorMessage()
    );
    // Saving before the LLM model is known would send reasoning_effort as null instead of the chosen value.
    readonly isLlmModelResolving = computed(
        () => this.activeTab() === 'llm' && (this.reasoningEffortField()?.resolving() ?? false)
    );
    readonly submitLabel = computed(() => {
        switch (this.activeTab()) {
            case 'llm':
                return 'Add LLM';
            case 'realtime':
                return 'Add Voice';
            case 'embedding':
                return 'Add Embedding';
        }
    });

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

    setActiveTab(tab: ConfigTab): void {
        this.activeTab.set(tab);
        this.errorMessage.set(null);
    }

    onSubmit(): void {
        // One save at a time, even when the tab was switched while another tab's save is in flight.
        if (this.isSaving()) return;
        switch (this.activeTab()) {
            case 'llm':
                this.submitLlm();
                break;
            case 'realtime':
                this.realtimeForm()?.submit();
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
        this.errorMessage.set(null);
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
                    const message = extractHttpErrorMessage(error, 'Failed to create LLM configuration.');
                    if (isClientError(error)) {
                        this.errorMessage.set(message);
                        return;
                    }
                    this.toast.error(message);
                },
            });
    }

    private submitEmbedding(): void {
        const { model, api_key_secret_id, custom_name, extra_headers } = this.embeddingForm.getRawValue();
        if (this.embeddingForm.invalid || model === null || this.isSubmitting()) {
            this.embeddingForm.markAllAsTouched();
            return;
        }
        // Cleared before the duplicate-name check, so an old refusal does not sit beside its toast.
        this.errorMessage.set(null);

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
                    const fallback = 'Failed to create embedding configuration.';
                    if (isClientError(error)) {
                        this.errorMessage.set(extractHttpErrorMessage(error, fallback));
                        return;
                    }
                    this.toast.error(fallback);
                },
            });
    }

    onCancel(): void {
        this.dialogRef.close(null);
    }
}
