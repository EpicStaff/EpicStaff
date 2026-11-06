import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    input,
    OnInit,
    output,
    signal,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    BinnedSecretNoteComponent,
    CustomInputComponent,
    GroupedPickerComponent,
    GroupedPickerGroup,
    GroupedPickerItem,
    GroupedPickerKey,
    HintMessageComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { SYSTEM_ONE_MODELS } from '@shared/constants';
import { SystemOneConfig, SystemOneConfigWrite, SystemOneProvider } from '@shared/models';
import { LlmConfigStorageService, SecretsStorageService, SystemOneConfigStorageService } from '@shared/services';
import { extractHttpErrorMessage, getProviderIconPath, isClientError, trackPickedSecrets } from '@shared/utils';

type KeyProvider = Exclude<SystemOneProvider, 'llm'>;

/** What answers the questions: a pinned model run with your API key, or one of your LLM configs. */
type ModelChoice = { provider: KeyProvider; modelName: string } | { provider: 'llm'; llmConfig: number };

interface ModelChoiceItem extends GroupedPickerItem {
    choice: ModelChoice;
}

const PROVIDER_NAMES: Record<SystemOneProvider, string> = { typesafe: 'TypeSafe', openai: 'OpenAI', llm: 'LLM' };

function providerGroup(provider: SystemOneProvider, items: ModelChoiceItem[]): GroupedPickerGroup<ModelChoiceItem> {
    return { id: provider, name: PROVIDER_NAMES[provider], icon: getProviderIconPath(provider), items };
}

function modelItems(provider: KeyProvider): ModelChoiceItem[] {
    return SYSTEM_ONE_MODELS[provider].map((modelName) => ({
        id: modelName,
        name: modelName,
        choice: { provider, modelName },
    }));
}

/** An edited config's model, falling back to its provider's first model when it has none. */
function choiceOf(config: SystemOneConfig): ModelChoice | null {
    if (config.provider === 'llm') {
        return config.llm_config === null ? null : { provider: 'llm', llmConfig: config.llm_config };
    }
    return { provider: config.provider, modelName: config.model_name ?? SYSTEM_ONE_MODELS[config.provider][0] };
}

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
        GroupedPickerComponent,
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
    protected readonly selectedProvider = computed(() => this.choice()?.provider ?? null);
    /** TypeSafe and OpenAI answer with a model and your API key; LLM answers with one of your LLM configs. */
    protected readonly usesKey = computed(
        () => this.selectedProvider() === 'typesafe' || this.selectedProvider() === 'openai'
    );
    protected readonly hasLlmConfigs = computed(() => this.llmConfigStorage.configs().length > 0);
    /** An edited config offers only its own provider's models. */
    protected readonly groups = computed(() => {
        const llmItems = this.llmConfigStorage.configs().map(
            (config): ModelChoiceItem => ({
                id: config.id,
                name: config.custom_name,
                choice: { provider: 'llm', llmConfig: config.id },
            })
        );
        const groups = [
            providerGroup('typesafe', modelItems('typesafe')),
            providerGroup('openai', modelItems('openai')),
            providerGroup('llm', llmItems),
        ];
        const fixedProvider = this.config()?.provider;
        return fixedProvider ? groups.filter((group) => group.id === fixedProvider) : groups;
    });
    protected readonly selectedKey = computed<GroupedPickerKey | null>(() => {
        const choice = this.choice();
        if (!choice) return null;
        return {
            groupId: choice.provider,
            itemId: choice.provider === 'llm' ? choice.llmConfig : choice.modelName,
        };
    });
    protected readonly apiKeyItems = computed<SelectItem[]>(() =>
        this.secretsStorage.selectItems(this.pickedApiKeyIds())
    );

    protected readonly form = new FormGroup({
        custom_name: new FormControl('', { nonNullable: true, validators: Validators.required }),
        model: new FormControl<ModelChoice | null>(null, Validators.required),
        api_key_secret_id: new FormControl<number | null>(null, Validators.required),
    });

    private readonly choice = toSignal(this.form.controls.model.valueChanges, { initialValue: null });
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
                model: choiceOf(config),
                api_key_secret_id: config.api_key_secret_id,
            });
        }
        this.toggleApiKey();

        trackPickedSecrets(this.form, ['api_key_secret_id'], this.pickedApiKeyIds, this.destroyRef);
        this.secretsStorage
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ error: () => {} });
        if ((config?.provider ?? 'llm') === 'llm') {
            this.llmConfigStorage
                .getAllConfigs()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({ error: () => {} });
        }
    }

    /** Validates the active provider's fields and creates or updates the config; emits `saved` on success. */
    submit(): void {
        if (this.isSubmitting()) return;
        const choice = this.choice();
        if (this.form.invalid || !choice) {
            this.form.markAllAsTouched();
            return;
        }

        const id = this.config()?.id;
        const body = this.buildBody(choice);
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

    /** Switching between TypeSafe and OpenAI keeps the picked secret. */
    protected pick(item: ModelChoiceItem): void {
        this.form.controls.model.setValue(item.choice);
        this.toggleApiKey();
        this.errorMessage.set(null);
    }

    /** Only a key-based provider's secret is validated and sent; LLM sends none. */
    private toggleApiKey(): void {
        const apiKey = this.form.controls.api_key_secret_id;
        if (this.usesKey()) apiKey.enable();
        else apiKey.disable();
    }

    private buildBody(choice: ModelChoice): SystemOneConfigWrite {
        const { custom_name, api_key_secret_id } = this.form.getRawValue();
        return choice.provider === 'llm'
            ? { custom_name, provider: 'llm', model_name: null, api_key_secret_id: null, llm_config: choice.llmConfig }
            : {
                  custom_name,
                  provider: choice.provider,
                  model_name: choice.modelName,
                  api_key_secret_id,
                  llm_config: null,
              };
    }
}
