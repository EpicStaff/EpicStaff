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
import { DEFAULT_STEP_SIZE, TOKEN_PRICE_HINT } from '@shared/constants';
import { EnterSubmitDirective } from '@shared/directives';
import { pricePairValidator } from '@shared/form-validators';
import { GetLlmConfigRequest, ModelTypes, ReasoningEffort } from '@shared/models';
import { LlmConfigStorageService, SecretsStorageService } from '@shared/services';
import {
    extractFieldErrorMessages,
    extractHttpErrorMessage,
    perMillionToPerToken,
    perTokenToPerMillion,
    trackPickedSecrets,
} from '@shared/utils';
import { startWith } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { InputNumberComponent } from '../../app-input-number/input-number.component';
import { ValidationErrorsComponent } from '../../app-validation-errors/validation-errors.component';
import { BinnedSecretNoteComponent } from '../../binned-secret-note/binned-secret-note.component';
import { ButtonComponent, IconButtonComponent } from '../../buttons';
import { CustomInputComponent } from '../../form-input/form-input.component';
import { HintMessageComponent } from '../../hint-message/hint-message.component';
import { JsonEditorFormFieldComponent } from '../../json-editor/json-editor-form-field.component';
import { KeyValueListComponent } from '../../key-value-list/key-value-list.component';
import { SelectComponent, SelectItem } from '../../select/select.component';
import { SliderWithStepperComponent } from '../../slider-with-stepper/slider-with-stepper.component';
import { LlmModelSelectorComponent } from '../llm-model-selector/llm-model-selector.component';
import { LlmReasoningEffortFieldComponent } from '../llm-reasoning-effort-field/llm-reasoning-effort-field.component';

interface DialogData {
    configId?: number;
}

@Component({
    selector: 'app-llm-model-config',
    templateUrl: './llm-model-config-dialog.component.html',
    styleUrls: ['./llm-model-config-dialog.component.scss'],
    imports: [
        BinnedSecretNoteComponent,
        IconButtonComponent,
        ButtonComponent,
        ReactiveFormsModule,
        CustomInputComponent,
        KeyValueListComponent,
        SliderWithStepperComponent,
        InputNumberComponent,
        ValidationErrorsComponent,
        LlmModelSelectorComponent,
        JsonEditorFormFieldComponent,
        SelectComponent,
        HintMessageComponent,
        EnterSubmitDirective,
        LlmReasoningEffortFieldComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmModelConfigDialogComponent implements OnInit {
    private readonly reasoningEffortField = viewChild(LlmReasoningEffortFieldComponent);

    private fb = inject(FormBuilder);
    private destroyRef = inject(DestroyRef);
    private configStorageService = inject(LlmConfigStorageService);
    private secretsStorageService = inject(SecretsStorageService);
    private toast = inject(ToastService);
    private data = inject<DialogData>(DIALOG_DATA, { optional: true });
    // Prices as stored, so an untouched price is sent back unchanged instead of through the per-1M conversion.
    private storedPrices: Pick<GetLlmConfigRequest, 'input_cost_per_token' | 'output_cost_per_token'> | null = null;

    dialogRef = inject(DialogRef);

    isSaving = signal<boolean>(false);
    isLoading = signal<boolean>(false);
    errorMessage = signal<string | null>(null);
    // FormGroup.invalid is a plain property: on this OnPush view it would keep showing the state from before the
    // reasoning-effort field cleared its server error in the same pass. Fed from statusChanges in ngOnInit.
    private readonly isFormInvalid = signal(false);

    isEditMode = computed(() => !!this.data?.configId);
    // Saving before the model is known would send reasoning_effort as null and erase a stored value.
    readonly isModelResolving = computed(() => this.reasoningEffortField()?.resolving() ?? false);
    title = computed(() => (this.isEditMode() ? 'Edit LLM Configuration' : 'Add LLM Configuration'));
    saveLabel = computed(() => (this.isEditMode() ? 'Save Changes' : 'Add LLM'));
    protected readonly isSaveDisabled = computed(
        () => this.isFormInvalid() || this.isSaving() || this.isLoading() || this.isModelResolving()
    );

    /** Secret ids picked in this form: a picked secret in the recycle bin keeps its option. */
    private readonly pickedSecretIds = signal<number[]>([]);
    secretItems = computed<SelectItem[]>(() => this.secretsStorageService.selectItems(this.pickedSecretIds()));

    protected readonly modelControl = new FormControl<number | null>(null, [Validators.required]);
    protected readonly selectedModelId = toSignal(this.modelControl.valueChanges, {
        initialValue: this.modelControl.value,
    });
    protected readonly reasoningEffortControl = new FormControl<ReasoningEffort | null>(null);
    form!: FormGroup;

    ngOnInit() {
        this.form = this.fb.group({
            custom_name: ['', [Validators.required]],
            api_key_secret_id: [null],
            model: this.modelControl,
            temperature: [null, [Validators.min(0), Validators.max(1)]],
            top_p: [null, [Validators.min(0.1)]],
            stop: [null],
            max_tokens: [4096, [Validators.min(500), Validators.max(2147483647)]],
            presence_penalty: [0],
            frequency_penalty: [0],
            logit_bias: [null],
            seed: [null, [Validators.min(-2147483648), Validators.max(2147483647)]],
            extra_headers: [{}],
            timeout: [120, [Validators.min(1), Validators.max(600)]],
            reasoning_effort: this.reasoningEffortControl,
            is_visible: [true],
            pricing: this.fb.group(
                {
                    input_price_per_million: [null as number | null, [Validators.min(0)]],
                    output_price_per_million: [null as number | null, [Validators.min(0)]],
                },
                { validators: pricePairValidator('input_price_per_million', 'output_price_per_million') }
            ),
        });
        this.form.statusChanges
            .pipe(startWith(this.form.status), takeUntilDestroyed(this.destroyRef))
            .subscribe((status) => this.isFormInvalid.set(status === 'INVALID'));
        trackPickedSecrets(this.form, ['api_key_secret_id'], this.pickedSecretIds, this.destroyRef);

        if (this.data?.configId) {
            this.loadConfig(this.data.configId);
        }

        this.secretsStorageService
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                error: () => this.toast.error('Failed to load secrets.'),
            });

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onSave();
            }
        });
    }

    private loadConfig(configId: number): void {
        this.isLoading.set(true);
        this.configStorageService
            .getConfigById(configId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (config) => {
                    this.storedPrices = {
                        input_cost_per_token: config.input_cost_per_token ?? null,
                        output_cost_per_token: config.output_cost_per_token ?? null,
                    };
                    this.form.patchValue({
                        ...config,
                        pricing: {
                            input_price_per_million: perTokenToPerMillion(config.input_cost_per_token),
                            output_price_per_million: perTokenToPerMillion(config.output_cost_per_token),
                        },
                    });
                    this.isLoading.set(false);
                },
                error: () => {
                    this.toast.error('Failed to load configuration.');
                    this.isLoading.set(false);
                },
            });
    }

    onCancel(): void {
        this.dialogRef.close();
    }

    onSave(): void {
        if (this.form.invalid || this.isSaving() || this.isLoading() || this.isModelResolving()) {
            this.form.markAllAsTouched();
            return;
        }

        this.isSaving.set(true);
        this.errorMessage.set(null);
        const { pricing, ...config } = this.form.value;
        const formValue = {
            ...config,
            reasoning_effort: this.reasoningEffortField()?.submittedValue() ?? null,
            input_cost_per_token: this.priceToSave(
                'input_price_per_million',
                pricing.input_price_per_million,
                this.storedPrices?.input_cost_per_token
            ),
            output_cost_per_token: this.priceToSave(
                'output_price_per_million',
                pricing.output_price_per_million,
                this.storedPrices?.output_cost_per_token
            ),
        };

        const request$ = this.isEditMode()
            ? this.configStorageService.updateConfig({ id: this.data!.configId!, ...formValue })
            : this.configStorageService.createConfig(formValue);

        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: () => {
                this.isSaving.set(false);
                this.toast.success(
                    this.isEditMode() ? 'Configuration updated successfully.' : 'Configuration created successfully.'
                );
                this.dialogRef.close();
            },
            error: (err: HttpErrorResponse) => {
                this.isSaving.set(false);
                const reasoningEffortErrors = extractFieldErrorMessages(err, 'reasoning_effort');
                if (
                    reasoningEffortErrors.length &&
                    this.reasoningEffortField()?.showServerErrors(reasoningEffortErrors)
                ) {
                    return;
                }
                this.errorMessage.set(extractHttpErrorMessage(err));
                console.error(err);
            },
        });
    }

    private priceToSave(
        controlName: string,
        pricePerMillion: number | null,
        storedPricePerToken: number | null | undefined
    ): number | null {
        const isEdited = this.form.get(['pricing', controlName])?.dirty ?? false;
        if (this.storedPrices && !isEdited) return storedPricePerToken ?? null;
        return perMillionToPerToken(pricePerMillion);
    }

    protected readonly ModelTypes = ModelTypes;
    protected readonly DEFAULT_STEP_SIZE = DEFAULT_STEP_SIZE;
    protected readonly TOKEN_PRICE_HINT = TOKEN_PRICE_HINT;
}
