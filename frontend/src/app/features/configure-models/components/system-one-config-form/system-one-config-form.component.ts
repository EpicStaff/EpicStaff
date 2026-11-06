import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    input,
    linkedSignal,
    OnInit,
    output,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AbstractControl, FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    BinnedSecretNoteComponent,
    CustomInputComponent,
    HelpTooltipComponent,
    HintMessageComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { JEV_MODEL_VERSIONS, SYSTEM_ONE_MODELS } from '@shared/constants';
import { SystemOneConfig, SystemOneConfigWrite, SystemOneProvider } from '@shared/models';
import { LlmConfigStorageService, SecretsStorageService, SystemOneConfigStorageService } from '@shared/services';
import { extractHttpErrorMessage, isClientError, trackPickedSecrets } from '@shared/utils';

const PROVIDERS: { key: SystemOneProvider; label: string }[] = [
    { key: 'typesafe', label: 'TypeSafe' },
    { key: 'openai', label: 'OpenAI' },
    { key: 'llm', label: 'LLM' },
];

/**
 * The fields of a System One configuration for each provider, and saving them. Used by both the
 * edit dialog and the "Add Configuration" dialog, which own the header and the Cancel / Save buttons.
 */
@Component({
    selector: 'app-system-one-config-form',
    imports: [
        ReactiveFormsModule,
        BinnedSecretNoteComponent,
        CustomInputComponent,
        HelpTooltipComponent,
        HintMessageComponent,
        SelectComponent,
        ValidationErrorsComponent,
    ],
    templateUrl: './system-one-config-form.component.html',
    styleUrls: ['./system-one-config-form.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SystemOneConfigFormComponent implements OnInit {
    /** The config to edit, read once on init; null creates a new one. Editing keeps the provider fixed. */
    readonly config = input<SystemOneConfig | null>(null);
    readonly saved = output<void>();

    readonly isSubmitting = signal(false);
    /** Why the last save failed, for the host dialog's error banner; cleared when a save starts. */
    readonly errorMessage = signal<string | null>(null);
    protected readonly selectedProvider = linkedSignal<SystemOneProvider>(() => this.config()?.provider ?? 'typesafe');
    protected readonly isEditMode = computed(() => this.config() !== null);
    /** TypeSafe and OpenAI answer with a model and your API key; LLM answers with one of your LLM configs. */
    protected readonly usesKey = computed(() => this.selectedProvider() !== 'llm');
    protected readonly modelItems = computed<SelectItem[]>(() => {
        const provider = this.selectedProvider();
        return provider === 'llm' ? [] : SYSTEM_ONE_MODELS[provider].map((model) => ({ name: model, value: model }));
    });
    protected readonly apiKeyItems = computed<SelectItem[]>(() =>
        this.secretsStorage.selectItems(this.pickedApiKeyIds())
    );
    protected readonly llmConfigItems = computed<SelectItem[]>(() =>
        this.llmConfigStorage.configs().map((config) => ({ name: config.custom_name, value: config.id }))
    );

    protected readonly providers = PROVIDERS;
    protected readonly form = new FormGroup({
        custom_name: new FormControl('', { nonNullable: true, validators: Validators.required }),
        model_name: new FormControl<string | null>(JEV_MODEL_VERSIONS[0], Validators.required),
        api_key_secret_id: new FormControl<number | null>(null, Validators.required),
        llm_config: new FormControl<number | null>(null, Validators.required),
    });

    private readonly pickedApiKeyIds = signal<number[]>([]);
    private readonly storage = inject(SystemOneConfigStorageService);
    private readonly secretsStorage = inject(SecretsStorageService);
    private readonly llmConfigStorage = inject(LlmConfigStorageService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        const config = this.config();
        if (config) {
            this.form.patchValue({
                custom_name: config.custom_name,
                model_name:
                    config.model_name ?? (config.provider === 'llm' ? null : SYSTEM_ONE_MODELS[config.provider][0]),
                api_key_secret_id: config.api_key_secret_id,
                llm_config: config.llm_config,
            });
        }
        this.applyProvider(this.selectedProvider());

        trackPickedSecrets(this.form, ['api_key_secret_id'], this.pickedApiKeyIds, this.destroyRef);
        this.secretsStorage
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ error: () => {} });
    }

    /** Validates the active provider's fields and creates or updates the config; emits `saved` on success. */
    submit(): void {
        if (this.isSubmitting()) return;
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }

        const id = this.config()?.id;
        const body = this.buildBody();
        this.isSubmitting.set(true);
        this.errorMessage.set(null);
        (id === undefined ? this.storage.createConfig(body) : this.storage.updateConfig(id, body))
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.isSubmitting.set(false);
                    this.saved.emit();
                },
                error: (error: HttpErrorResponse) => {
                    this.isSubmitting.set(false);
                    const fallback = 'Failed to save configuration.';
                    this.errorMessage.set(isClientError(error) ? extractHttpErrorMessage(error, fallback) : fallback);
                },
            });
    }

    protected selectProvider(provider: SystemOneProvider): void {
        if (this.isEditMode()) return;
        this.selectedProvider.set(provider);
        if (provider !== 'llm') this.form.controls.model_name.setValue(SYSTEM_ONE_MODELS[provider][0]);
        this.applyProvider(provider);
        this.errorMessage.set(null);
    }

    /** Only the active provider's fields are validated and sent; the other fields are disabled. */
    private applyProvider(provider: SystemOneProvider): void {
        const { model_name, api_key_secret_id, llm_config } = this.form.controls;
        const usesKey = provider !== 'llm';
        const toggle = (control: AbstractControl, enabled: boolean): void =>
            enabled ? control.enable() : control.disable();
        toggle(model_name, usesKey);
        toggle(api_key_secret_id, usesKey);
        toggle(llm_config, !usesKey);
        if (!usesKey) {
            this.llmConfigStorage
                .getAllConfigs()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({ error: () => {} });
        }
    }

    private buildBody(): SystemOneConfigWrite {
        const { custom_name, model_name, api_key_secret_id, llm_config } = this.form.getRawValue();
        const provider = this.selectedProvider();
        return provider === 'llm'
            ? { custom_name, provider, model_name: null, api_key_secret_id: null, llm_config }
            : { custom_name, provider, model_name, api_key_secret_id, llm_config: null };
    }
}
