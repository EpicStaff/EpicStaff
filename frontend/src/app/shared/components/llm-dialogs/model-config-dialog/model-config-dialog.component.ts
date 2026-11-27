import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { NgTemplateOutlet } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, OnInit, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { DEFAULT_STEP_SIZE, INPUT_TOKEN_PRICE_HINT, TOKEN_PRICE_HINT } from '@shared/constants';
import { EnterSubmitDirective } from '@shared/directives';
import { pricePairValidator } from '@shared/form-validators';
import {
    CatalogModel,
    CatalogProvider,
    ConfigFieldError,
    ConfigModelReference,
    CreateEmbeddingConfigRequest,
    EmbeddingConfig,
    GetLlmConfigRequest,
    JsonSchema,
    JsonSchemaProperty,
    ModelKind,
    ModelSchemas,
    REASONING_EFFORT_LABELS,
} from '@shared/models';
import {
    EmbeddingConfigStorageService,
    LlmConfigStorageService,
    ModelCatalogService,
    SecretsStorageService,
} from '@shared/services';
import {
    deepEqual,
    extractHttpErrorMessage,
    isClientError,
    perMillionToPerToken,
    perTokenToPerMillion,
    trackPickedSecrets,
} from '@shared/utils';
import { catchError, debounceTime, EMPTY, map, Observable, of, startWith, Subject, switchMap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { InputNumberComponent } from '../../app-input-number/input-number.component';
import { ValidationErrorsComponent } from '../../app-validation-errors/validation-errors.component';
import { BinnedSecretNoteComponent } from '../../binned-secret-note/binned-secret-note.component';
import { ButtonComponent, IconButtonComponent } from '../../buttons';
import { ErrorBannerComponent } from '../../error-banner/error-banner.component';
import { CustomInputComponent } from '../../form-input/form-input.component';
import { HintMessageComponent } from '../../hint-message/hint-message.component';
import { KeyValueListComponent } from '../../key-value-list/key-value-list.component';
import { SchemaFormComponent } from '../../schema-form/schema-form.component';
import { SelectComponent, SelectItem } from '../../select/select.component';
import { WarningNoteComponent } from '../../warning-note/warning-note.component';

/** The config kinds this dialog creates and edits; each has its own config table. */
export type ModelConfigKind = Extract<ModelKind, 'llm' | 'embedding'>;

/** Creates a config of `kind`, or edits the one with `configId`. */
export interface ModelConfigDialogData {
    kind: ModelConfigKind;
    configId?: number;
}

/** One setting or connection field fitted to the model, as the change list shows it. */
interface ParameterChange {
    name: string;
    text: string;
}

/** What an edited config was loaded with: an unchanged model is saved by its row id. */
interface LoadedConfig {
    modelId: number;
    provider: string | null;
    modelName: string | null;
    isVisible: boolean;
    inputCostPerToken: number | null;
    outputCostPerToken: number | null;
}

const KIND_LABELS: Record<ModelConfigKind, string> = { llm: 'LLM', embedding: 'Embedding' };
/** Select options shown by name instead of their raw value. */
const OPTION_LABELS: Record<string, Record<string, string>> = {
    reasoning_effort: REASONING_EFFORT_LABELS,
    reasoning_history: { disabled: 'Off', interleaved: 'Interleaved', preserved: 'Preserved' },
    context_length_exceeded_behavior: { error: 'Fail the request', truncate: 'Shorten the answer' },
};
/** Sample values for connection fields; neutral, as each provider's endpoint differs (a local Ollama is plain http). */
const CONNECTION_PLACEHOLDERS: Record<string, string> = { base_url: 'e.g. https://your-endpoint.example.com' };
const SCHEMA_LOAD_ERROR = "Failed to load the model's settings.";
const MODEL_SEARCH_DEBOUNCE_MS = 300;

/**
 * Creates or edits an LLM or embedding config: provider, then model, then the model's Connection and Settings, both
 * rendered from the catalog's schemas. Switching the model keeps the settings the new model takes (clamped to its
 * limits), drops the others and adds its new ones at their defaults, and lists what changed until the save. A stored
 * config is fitted to its own model the same way when it is opened, as a write with a setting the model does not list
 * is refused. Stored connection fields the model does not list are not shown, and go back unchanged with that model.
 */
@Component({
    selector: 'app-model-config-dialog',
    imports: [
        ReactiveFormsModule,
        BinnedSecretNoteComponent,
        ButtonComponent,
        CustomInputComponent,
        EnterSubmitDirective,
        ErrorBannerComponent,
        HintMessageComponent,
        IconButtonComponent,
        InputNumberComponent,
        KeyValueListComponent,
        NgTemplateOutlet,
        SchemaFormComponent,
        SelectComponent,
        ValidationErrorsComponent,
        WarningNoteComponent,
    ],
    templateUrl: './model-config-dialog.component.html',
    styleUrls: ['./model-config-dialog.component.scss'],
})
export class ModelConfigDialogComponent implements OnInit {
    private readonly parametersForm = viewChild<SchemaFormComponent>('parametersForm');

    // Ahead of the fields below, which are built from it.
    private readonly data = inject<ModelConfigDialogData>(DIALOG_DATA);
    protected readonly kind = this.data.kind;
    protected readonly configId = this.data.configId;
    protected readonly isEditMode = this.configId !== undefined;
    protected readonly isLlm = this.kind === 'llm';

    protected readonly form = new FormGroup({
        custom_name: new FormControl('', { nonNullable: true, validators: Validators.required }),
        provider: new FormControl<string | null>(null, Validators.required),
        // Enabled once a provider is chosen.
        model_name: new FormControl<string | null>({ value: null, disabled: true }, Validators.required),
        api_key_secret_id: new FormControl<number | null>(null, this.isLlm ? [] : [Validators.required]),
        timeout: new FormControl<number | null>(120, [Validators.min(1), Validators.max(600)]),
        extra_headers: new FormControl<Record<string, string>>({}, { nonNullable: true }),
        pricing: new FormGroup(
            {
                input_price_per_million: new FormControl<number | null>(null, Validators.min(0)),
                output_price_per_million: new FormControl<number | null>(null, Validators.min(0)),
            },
            { validators: pricePairValidator('input_price_per_million', 'output_price_per_million') }
        ),
    });

    /** An edited config is on its way: the body waits for it. */
    protected readonly isLoading = signal(this.isEditMode);
    protected readonly isSaving = signal(false);
    protected readonly isSchemaLoading = signal(false);
    protected readonly errorMessage = signal<string | null>(null);
    /** The server's refusal of the last save, per `parameters.*` / `connection.*` field the form shows. */
    protected readonly fieldErrors = signal<ConfigFieldError[]>([]);
    protected readonly providers = signal<CatalogProvider[]>([]);
    protected readonly catalogModels = signal<CatalogModel[]>([]);
    protected readonly schemas = signal<ModelSchemas | null>(null);
    protected readonly parameters = signal<Record<string, unknown>>({});
    protected readonly connection = signal<Record<string, unknown>>({});
    /** What fitting the settings to the model changed, on opening a stored config or on a switch; shown until the save. */
    protected readonly changes = signal<ParameterChange[]>([]);
    /** `changes` come from opening the stored config, not from a model switch. */
    protected readonly changesFromStored = signal(false);
    /** The edited config is marked for review. */
    protected readonly needsReview = signal(false);
    protected readonly reviewReasons = signal<string[]>([]);

    private readonly providerName = toSignal(this.form.controls.provider.valueChanges, { initialValue: null });
    private readonly modelName = toSignal(this.form.controls.model_name.valueChanges, { initialValue: null });
    private readonly isFormInvalid = toSignal(
        this.form.statusChanges.pipe(
            startWith(this.form.status),
            map((status) => status === 'INVALID')
        ),
        { requireSync: true }
    );
    /** Secret ids picked in this form: a picked secret in the recycle bin keeps its option. */
    private readonly pickedSecretIds = signal<number[]>([]);

    protected readonly title = `${this.isEditMode ? 'Edit' : 'Add'} ${KIND_LABELS[this.kind]} Configuration`;
    protected readonly saveLabel = this.isEditMode ? 'Save Changes' : `Add ${KIND_LABELS[this.kind]}`;
    protected readonly providerItems = computed<SelectItem[]>(() => {
        const items: SelectItem[] = this.providers().map((provider) => ({
            name: provider.label,
            value: provider.name,
            tip: provider.recommended ? 'Recommended' : undefined,
        }));
        const current = this.providerName();
        // A config may name its provider by an alias the catalog lists under another name.
        return current && !items.some((item) => item.value === current)
            ? [{ name: current, value: current }, ...items]
            : items;
    });
    protected readonly modelItems = computed<SelectItem[]>(() => {
        const items: SelectItem[] = this.catalogModels().map((model) => ({
            name: model.name,
            value: model.name,
            tip: model.custom ? 'Custom' : model.recommended ? 'Recommended' : undefined,
        }));
        const current = this.modelName();
        // A search can hide the chosen model, and a hidden custom or a deprecated one is not listed: keep it listed.
        return current && !items.some((item) => item.value === current)
            ? [{ name: current, value: current }, ...items]
            : items;
    });
    protected readonly allowsCustomModel = computed(
        () => this.providers().find((provider) => provider.name === this.providerName())?.custom_models ?? false
    );
    protected readonly hasConnectionFields = computed(
        () => Object.keys(this.schemas()?.connection.properties ?? {}).length > 0
    );
    protected readonly hasSettings = computed(
        () => Object.keys(this.schemas()?.parameters.properties ?? {}).length > 0
    );
    protected readonly isSaveDisabled = computed(
        () => this.isFormInvalid() || this.isSaving() || this.isLoading() || this.isSchemaLoading() || !this.schemas()
    );
    protected readonly secretItems = computed<SelectItem[]>(() =>
        this.secretsStorage.selectItems(this.pickedSecretIds())
    );
    protected readonly optionLabels = OPTION_LABELS;
    protected readonly connectionPlaceholders = CONNECTION_PLACEHOLDERS;
    protected readonly TOKEN_PRICE_HINT = TOKEN_PRICE_HINT;
    protected readonly INPUT_TOKEN_PRICE_HINT = INPUT_TOKEN_PRICE_HINT;
    protected readonly DEFAULT_STEP_SIZE = DEFAULT_STEP_SIZE;

    private readonly dialogRef = inject(DialogRef);
    private readonly catalog = inject(ModelCatalogService);
    private readonly llmConfigStorage = inject(LlmConfigStorageService);
    private readonly embeddingConfigStorage = inject(EmbeddingConfigStorageService);
    private readonly secretsStorage = inject(SecretsStorageService);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly modelSearches = new Subject<string>();
    private readonly modelQueries = new Subject<{ provider: string; search: string }>();
    /** `initial`: the edited config's own model. Null drops the answer still on its way. */
    private readonly schemaQueries = new Subject<{ provider: string; model: string; initial: boolean } | null>();
    private loaded: LoadedConfig | null = null;
    /** The provider the model list and the connection belong to. */
    private loadedProvider: string | null = null;
    /** The settings of the model before the current one, for the names of the ones a switch drops. */
    private previousProperties: Record<string, JsonSchemaProperty> = {};
    /** Stored connection fields the config's own model does not list: resent unchanged while that model stays. */
    private undeclaredConnection: Record<string, unknown> = {};

    constructor() {
        this.modelSearches.pipe(debounceTime(MODEL_SEARCH_DEBOUNCE_MS), takeUntilDestroyed()).subscribe((search) => {
            if (this.loadedProvider) this.modelQueries.next({ provider: this.loadedProvider, search });
        });
        this.modelQueries
            .pipe(
                switchMap(({ provider, search }) =>
                    this.catalog.models(this.kind, provider, search).pipe(catchError(() => of([])))
                ),
                takeUntilDestroyed()
            )
            .subscribe((models) => this.catalogModels.set(models));
        this.schemaQueries
            .pipe(
                switchMap((query) => {
                    // A new model or provider: the last model's failed load no longer applies. Any other banner (a
                    // refused save, the providers' failed load) stays.
                    if (this.errorMessage() === SCHEMA_LOAD_ERROR) this.errorMessage.set(null);
                    return (query ? this.catalog.schemas(this.kind, query.provider, query.model) : EMPTY).pipe(
                        map((schemas) => ({ schemas, initial: !!query?.initial })),
                        catchError(() => {
                            this.isSchemaLoading.set(false);
                            this.errorMessage.set(SCHEMA_LOAD_ERROR);
                            return EMPTY;
                        })
                    );
                }),
                takeUntilDestroyed()
            )
            .subscribe(({ schemas, initial }) => this.applySchemas(schemas, initial));
    }

    ngOnInit(): void {
        trackPickedSecrets(this.form, ['api_key_secret_id'], this.pickedSecretIds, this.destroyRef);
        this.secretsStorage
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ error: () => this.toast.error('Failed to load secrets.') });
        this.catalog
            .providers(this.kind)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (providers) => this.providers.set(providers),
                error: () => this.errorMessage.set('Failed to load the providers.'),
            });
        if (this.configId !== undefined) this.loadConfig(this.configId);

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onSave();
            }
        });
    }

    protected onProviderChange(): void {
        const provider = this.form.controls.provider.value;
        if (provider === this.loadedProvider) return;
        this.loadedProvider = provider;
        this.form.controls.model_name.reset({ value: null, disabled: !provider });
        this.rememberSettings();
        // A model's schemas still on their way belong to the provider that was left.
        this.schemaQueries.next(null);
        this.isSchemaLoading.set(false);
        this.schemas.set(null);
        this.connection.set({});
        this.catalogModels.set([]);
        if (provider) this.modelQueries.next({ provider, search: '' });
    }

    protected onModelSearch(search: string): void {
        this.modelSearches.next(search);
    }

    protected onModelChange(): void {
        const provider = this.form.controls.provider.value;
        const model = this.form.controls.model_name.value;
        if (!provider || !model) return;
        this.rememberSettings();
        this.isSchemaLoading.set(true);
        this.schemaQueries.next({ provider, model, initial: false });
    }

    protected onParametersChange(value: Record<string, unknown>): void {
        this.clearEditedErrors('parameters', this.parameters(), value);
        this.parameters.set(value);
    }

    protected onConnectionChange(value: Record<string, unknown>): void {
        this.clearEditedErrors('connection', this.connection(), value);
        this.connection.set(value);
    }

    /** Puts every setting back to the model's default. */
    protected onSetDefaults(): void {
        this.parametersForm()?.resetAll();
    }

    protected onCancel(): void {
        this.dialogRef.close();
    }

    protected onSave(): void {
        if (this.isSaveDisabled()) {
            this.form.markAllAsTouched();
            return;
        }
        const value = this.form.getRawValue();
        const customName = value.custom_name.trim();
        this.errorMessage.set(null);

        const reference = this.modelReference(value.provider!, value.model_name!);
        const fields = {
            ...reference,
            custom_name: customName,
            api_key_secret_id: value.api_key_secret_id,
            extra_headers: value.extra_headers,
            parameters: this.parameters(),
            connection: { ...this.undeclaredConnection, ...this.connection() },
            is_visible: this.loaded?.isVisible ?? true,
        };
        this.isSaving.set(true);
        this.fieldErrors.set([]);
        this.saveRequest(fields, value.timeout, value.pricing)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.isSaving.set(false);
                    this.toast.success(
                        this.isEditMode ? 'Configuration updated successfully.' : 'Configuration created successfully.'
                    );
                    this.dialogRef.close(true);
                },
                error: (error: HttpErrorResponse) => this.onSaveError(error),
            });
    }

    private loadConfig(configId: number): void {
        this.isLoading.set(true);
        this.configWithModel(configId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: ({ config, provider, modelName }) => {
                    this.loaded = {
                        modelId: config.model,
                        provider,
                        modelName,
                        isVisible: config.is_visible,
                        inputCostPerToken: 'input_cost_per_token' in config ? config.input_cost_per_token : null,
                        outputCostPerToken: 'output_cost_per_token' in config ? config.output_cost_per_token : null,
                    };
                    this.form.patchValue({
                        custom_name: config.custom_name,
                        provider,
                        model_name: modelName,
                        api_key_secret_id: config.api_key_secret_id,
                        extra_headers: config.extra_headers ?? {},
                        timeout: 'timeout' in config ? config.timeout : null,
                        pricing: {
                            input_price_per_million: perTokenToPerMillion(this.loaded.inputCostPerToken),
                            output_price_per_million: perTokenToPerMillion(this.loaded.outputCostPerToken),
                        },
                    });
                    this.parameters.set(config.parameters);
                    this.connection.set(config.connection);
                    this.needsReview.set(config.needs_review);
                    this.reviewReasons.set(config.review_reasons);
                    this.loadedProvider = provider;
                    this.isLoading.set(false);
                    // A config whose model is gone has none to look up: the user picks one, as in a new config.
                    if (!provider) return;
                    this.form.controls.model_name.enable();
                    this.modelQueries.next({ provider, search: '' });
                    if (!modelName) return;
                    this.isSchemaLoading.set(true);
                    this.schemaQueries.next({ provider, model: modelName, initial: true });
                },
                // Nothing to edit: a form left open would save blanks over the config.
                error: () => {
                    this.toast.error('Failed to load configuration.');
                    this.dialogRef.close();
                },
            });
    }

    /** The config, and the catalog names of its provider and model, which it carries itself (null once it has none). */
    private configWithModel(configId: number): Observable<{
        config: GetLlmConfigRequest | EmbeddingConfig;
        provider: string | null;
        modelName: string | null;
    }> {
        const config$: Observable<GetLlmConfigRequest | EmbeddingConfig> = this.isLlm
            ? this.llmConfigStorage.getConfigById(configId)
            : this.embeddingConfigStorage.getConfigById(configId);
        return config$.pipe(map((config) => ({ config, provider: config.provider, modelName: config.model_name })));
    }

    private applySchemas(schemas: ModelSchemas, initial: boolean): void {
        const model = initial ? 'the model' : 'the new model';
        const fitted = this.hasModel()
            ? fitParameters(this.parameters(), schemas.parameters, schemas.defaults, this.previousProperties, model)
            : { parameters: { ...schemas.defaults }, changes: [] };
        const connectionFields = schemas.connection.properties;
        const undeclared = initial
            ? Object.fromEntries(Object.entries(this.connection()).filter(([name]) => !(name in connectionFields)))
            : {};
        // What only the config's own model was sent goes with a switch, and is listed.
        const dropped = initial ? [] : Object.keys(this.undeclaredConnection);
        this.undeclaredConnection = undeclared;
        this.parameters.set(fitted.parameters);
        this.changes.set([
            ...fitted.changes,
            ...dropped.map((name) => ({
                name: `connection.${name}`,
                text: `${name}: connection field removed, ${model} does not use it`,
            })),
        ]);
        this.changesFromStored.set(initial);
        this.connection.update((connection) =>
            Object.fromEntries(Object.entries(connection).filter(([name]) => name in connectionFields))
        );
        this.fieldErrors.set([]);
        this.schemas.set(schemas);
        this.isSchemaLoading.set(false);
    }

    /** A model was chosen before: its settings are what a switch keeps. */
    private hasModel(): boolean {
        return Object.keys(this.previousProperties).length > 0 || this.loaded !== null;
    }

    private rememberSettings(): void {
        const properties = this.schemas()?.parameters.properties;
        if (properties) this.previousProperties = { ...this.previousProperties, ...properties };
    }

    /** The edited config's own model goes by its row id; any other by provider and name. */
    private modelReference(provider: string, modelName: string): ConfigModelReference {
        const loaded = this.loaded;
        return loaded && loaded.provider === provider && loaded.modelName === modelName
            ? { model: loaded.modelId }
            : { provider, model_name: modelName };
    }

    private saveRequest(
        fields: CreateEmbeddingConfigRequest,
        timeout: number | null,
        pricing: { input_price_per_million: number | null; output_price_per_million: number | null }
    ): Observable<unknown> {
        const id = this.configId;
        if (!this.isLlm) {
            return id === undefined
                ? this.embeddingConfigStorage.createConfig(fields)
                : this.embeddingConfigStorage.updateConfig({ ...fields, id });
        }
        const llmFields = {
            ...fields,
            timeout,
            input_cost_per_token: this.priceToSave(
                'input_price_per_million',
                pricing.input_price_per_million,
                this.loaded?.inputCostPerToken
            ),
            output_cost_per_token: this.priceToSave(
                'output_price_per_million',
                pricing.output_price_per_million,
                this.loaded?.outputCostPerToken
            ),
        };
        return id === undefined
            ? this.llmConfigStorage.createConfig(llmFields)
            : this.llmConfigStorage.updateConfig({ ...llmFields, id });
    }

    /** An untouched stored price goes back as stored, not through the per-1M conversion. */
    private priceToSave(
        controlName: 'input_price_per_million' | 'output_price_per_million',
        pricePerMillion: number | null,
        storedPricePerToken: number | null | undefined
    ): number | null {
        if (this.loaded && !this.form.controls.pricing.controls[controlName].dirty) return storedPricePerToken ?? null;
        return perMillionToPerToken(pricePerMillion);
    }

    private onSaveError(error: HttpErrorResponse): void {
        this.isSaving.set(false);
        const errors = responseFieldErrors(error);
        if (errors.some(isSettingsError)) {
            const shown = errors.filter((item) => this.isShownField(item.field));
            this.fieldErrors.set(shown);
            // An error with no field on screen to sit under is said in the banner, never dropped.
            const others = errors.filter((item) => !shown.includes(item));
            if (others.length > 0) {
                this.errorMessage.set(others.map((item) => `${item.field}: ${item.reason}`).join(' '));
            }
            return;
        }
        const fallback = this.isEditMode ? 'Configuration update failed.' : 'Configuration creation failed.';
        if (isClientError(error)) {
            this.errorMessage.set(extractHttpErrorMessage(error, fallback));
            return;
        }
        this.toast.error(fallback);
    }

    /** `field` (`parameters.<name>` or `connection.<name>`) has a control in the form the current schemas render. */
    private isShownField(field: string): boolean {
        const schemas = this.schemas();
        const separator = field.indexOf('.');
        const path = field.slice(0, separator);
        if (!schemas || (path !== 'parameters' && path !== 'connection')) return false;
        return field.slice(separator + 1) in schemas[path].properties;
    }

    /** Drops the server's error of each `path` field whose value the user just changed. */
    private clearEditedErrors(path: string, before: Record<string, unknown>, after: Record<string, unknown>): void {
        if (this.fieldErrors().length === 0) return;
        this.fieldErrors.update((errors) =>
            errors.filter((item) => {
                if (!item.field.startsWith(`${path}.`)) return true;
                const name = item.field.slice(path.length + 1);
                return deepEqual(before[name], after[name]);
            })
        );
    }
}

/** The errors of a refused save that name a field. */
function responseFieldErrors(error: HttpErrorResponse): ConfigFieldError[] {
    const errors: unknown = (error.error as { errors?: unknown } | null)?.errors;
    return Array.isArray(errors) ? (errors as unknown[]).filter(isFieldError) : [];
}

function isFieldError(item: unknown): item is ConfigFieldError {
    if (typeof item !== 'object' || item === null || !('field' in item) || !('reason' in item)) return false;
    return typeof item.reason === 'string' && typeof item.field === 'string';
}

/** The error names a setting or a connection field. */
function isSettingsError(item: ConfigFieldError): boolean {
    return item.field.startsWith('parameters.') || item.field.startsWith('connection.');
}

/**
 * The settings fitted to a model (`model`: how the change list names it): a value it takes is kept (a number clamped
 * to its limits, a choice it does not offer back to its default), one it does not take is dropped, and one of its own
 * that is missing starts at its default.
 */
function fitParameters(
    current: Record<string, unknown>,
    schema: JsonSchema,
    defaults: Record<string, unknown>,
    previousProperties: Record<string, JsonSchemaProperty>,
    model: string
): { parameters: Record<string, unknown>; changes: ParameterChange[] } {
    const parameters: Record<string, unknown> = {};
    const changes: ParameterChange[] = [];
    for (const [name, value] of Object.entries(current)) {
        const property = schema.properties[name];
        if (!property) {
            const label = previousProperties[name]?.title ?? name;
            changes.push({ name, text: `${label}: removed, ${model} does not support it` });
            continue;
        }
        const fitted = fitValue(value, property, defaults[name]);
        if (fitted !== null) parameters[name] = fitted;
        if (!deepEqual(fitted, value)) {
            changes.push({
                name,
                text: `${property.title ?? name}: ${formatValue(name, value, property)} → ${formatValue(
                    name,
                    fitted,
                    property
                )}`,
            });
        }
    }
    for (const [name, value] of Object.entries(defaults)) {
        const property = schema.properties[name];
        if (name in current || !property) continue;
        parameters[name] = value;
        changes.push({ name, text: `${property.title ?? name}: added, set to ${formatValue(name, value, property)}` });
    }
    return { parameters, changes };
}

/** `value` within what `property` allows: a number clamped to its limits, an unknown choice replaced by the default. */
function fitValue(value: unknown, property: JsonSchemaProperty, defaultValue: unknown): unknown {
    if (typeof value === 'number') {
        return Math.min(property.maximum ?? Infinity, Math.max(property.minimum ?? -Infinity, value));
    }
    if (property.enum && !property.enum.includes(value as string | null)) return defaultValue ?? null;
    return value;
}

/** `value` as its control shows it: a percent setting in percent, a choice by its display name. */
function formatValue(name: string, value: unknown, property: JsonSchemaProperty): string {
    if (value === null || value === undefined) return 'not set';
    if (typeof value === 'number' && property['x-widget'] === 'percent') {
        return `${Number((value * (property['x-scale'] ?? 100)).toFixed(2))}%`;
    }
    if (typeof value === 'string') return OPTION_LABELS[name]?.[value] ?? value;
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
}
