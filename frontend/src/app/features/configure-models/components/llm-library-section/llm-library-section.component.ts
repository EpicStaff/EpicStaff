import { Dialog } from '@angular/cdk/dialog';
import { ComponentType } from '@angular/cdk/portal';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    Injector,
    OnInit,
    Signal,
    signal,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import {
    AppSvgIconComponent,
    AuthorshipDetailsDialogService,
    AuthorshipDetailsSource,
    BulkSelectDropdownComponent,
    ButtonComponent,
    EmbeddingModelConfigDialogComponent,
    FetchErrorStateComponent,
    LlmModelConfigDialogComponent,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectComponent,
    SelectItem,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import {
    ActionCode,
    BulkDeleteGroup,
    BulkDeleteLabel,
    BulkDeleteOutcome,
    BulkDeleteTarget,
    LlmLibraryModel,
    LlmLibraryProviderGroup,
    ModelTypes,
    ResourceCode,
    SystemOneConfig,
} from '@shared/models';
import {
    BulkDeleteService,
    EmbeddingConfigStorageService,
    LlmConfigStorageService,
    LLMLibraryService,
    SystemOneConfigStorageService,
} from '@shared/services';
import { takeQueryParams } from '@shared/utils';
import { forkJoin, Observable, of } from 'rxjs';
import { catchError, finalize, tap } from 'rxjs/operators';

import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { DefaultModelsStorageService } from '../../services/default-models-storage.service';
import { ElevenLabsRealtimeConfigStorageService } from '../../services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../services/llms/openai-realtime-config-storage.service';
import {
    llmLibraryBulkDeleteGroups,
    LlmLibraryBulkDeleteSource,
    llmLibrarySelectionKey,
    LlmLibrarySelectionKind,
} from '../../utils/llm-library-bulk-delete.util';
import { AddConfigurationDialogComponent } from '../add-configuration-dialog/add-configuration-dialog.component';
import {
    LlmLibraryCardComponent,
    LlmLibraryCardViewDetailsEvent,
} from '../llm-library-card/llm-library-card.component';
import {
    RealtimeConfigDialogComponent,
    RealtimeConfigDialogData,
} from '../realtime-config-dialog/realtime-config-dialog.component';
import { RealtimeConfig, RealtimeProvider } from '../realtime-config-form/realtime-config-form.component';
import {
    SystemOneConfigDialogComponent,
    SystemOneConfigDialogData,
} from '../system-one-config-dialog/system-one-config-dialog.component';

/** Voice configs have no tags, temperature or deprecation, so the shared card shows only their names. */
function toVoiceCardModel(config: RealtimeConfig): LlmLibraryModel {
    return {
        id: config.id,
        customName: config.custom_name,
        modelName: config.model_name,
        tags: [],
        temperature: null,
        usedByCount: null,
        configType: ModelTypes.REALTIME,
        isDeprecated: false,
    };
}

/** `llmConfigName` is the LLM config an LLM-provider config answers with; the card does not show `configType`. */
function toSystemOneCardModel(config: SystemOneConfig, llmConfigName: string | undefined): LlmLibraryModel {
    return {
        id: config.id,
        customName: config.custom_name,
        modelName: config.provider === 'llm' ? `LLM: ${llmConfigName ?? 'not set'}` : (config.model_name ?? ''),
        tags: [],
        temperature: null,
        usedByCount: null,
        configType: ModelTypes.LLM,
        isDeprecated: false,
    };
}

interface VoiceProvider {
    key: RealtimeProvider;
    label: string;
    deleteLabel: BulkDeleteLabel;
    storage: {
        configs: Signal<RealtimeConfig[]>;
        getAllConfigs(force?: boolean): Observable<unknown[]>;
    } & BulkDeleteTarget;
}

type SectionKey = 'llm' | 'embedding' | 'realtime' | 'transcription' | 'system_one' | RealtimeProvider;

/** A config a `?configType=&configId=` link points at: its name, and how its Edit button opens it. */
interface LinkedConfig {
    name: string;
    open: () => void;
}

/** The voice provider each voice `configType` of a link names. */
const VOICE_CONFIG_TYPES = new Map<string, RealtimeProvider>([
    ['openai-voice', 'openai'],
    ['elevenlabs-voice', 'elevenlabs'],
    ['gemini-voice', 'gemini'],
]);

/** The card type each LLM-library `configType` of a link names. */
const MODEL_CONFIG_TYPES = new Map<string, ModelTypes>([
    ['llm', ModelTypes.LLM],
    ['embedding', ModelTypes.EMBEDDING],
]);

const SYSTEM_ONE_LABEL = 'System One Configs';
const LLM_BULK_DELETE_LABEL: BulkDeleteLabel = { singular: 'LLM config', plural: 'LLM configs' };
const EMBEDDING_BULK_DELETE_LABEL: BulkDeleteLabel = { singular: 'embedding config', plural: 'embedding configs' };
const SYSTEM_ONE_BULK_DELETE_LABEL: BulkDeleteLabel = { singular: 'System One config', plural: 'System One configs' };

@Component({
    selector: 'app-llm-library-section',
    imports: [
        FormsModule,
        LlmLibraryCardComponent,
        AppSvgIconComponent,
        LoadingSpinnerComponent,
        SelectComponent,
        HasPermissionDirective,
        ButtonComponent,
        BulkSelectDropdownComponent,
        SearchComponent,
        FetchErrorStateComponent,
    ],
    templateUrl: './llm-library-section.component.html',
    styleUrls: ['./llm-library-section.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmLibrarySectionComponent implements OnInit {
    private readonly addButton = viewChild('addButton', { read: ButtonComponent });

    private readonly llmLibraryService = inject(LLMLibraryService);
    private readonly llmConfigStorageService = inject(LlmConfigStorageService);
    private readonly embeddingConfigStorage = inject(EmbeddingConfigStorageService);
    private readonly openaiRealtimeStorage = inject(OpenAIRealtimeConfigStorageService);
    private readonly elevenLabsRealtimeStorage = inject(ElevenLabsRealtimeConfigStorageService);
    private readonly geminiRealtimeStorage = inject(GeminiRealtimeConfigStorageService);
    private readonly systemOneStorage = inject(SystemOneConfigStorageService);
    private readonly authorshipDetailsDialog = inject(AuthorshipDetailsDialogService);
    private readonly defaultModelsStorageService = inject(DefaultModelsStorageService);
    private readonly bulkDeleteService = inject(BulkDeleteService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly dialog = inject(Dialog);
    private readonly injector = inject(Injector);
    private readonly permissions = inject(PermissionsService);
    private readonly route = inject(ActivatedRoute);
    private readonly router = inject(Router);
    // `?configType=&configId=`, taken from the URL at init and opened after the first load
    private linkedConfigParams: Partial<Record<'configType' | 'configId', string>> = {};

    readonly voiceProviders: VoiceProvider[] = [
        {
            key: 'openai',
            label: 'OpenAI Voice Configs',
            deleteLabel: { singular: 'OpenAI voice config', plural: 'OpenAI voice configs' },
            storage: this.openaiRealtimeStorage,
        },
        {
            key: 'elevenlabs',
            label: 'ElevenLabs Voice Configs',
            deleteLabel: { singular: 'ElevenLabs voice config', plural: 'ElevenLabs voice configs' },
            storage: this.elevenLabsRealtimeStorage,
        },
        {
            key: 'gemini',
            label: 'Gemini Voice Configs',
            deleteLabel: { singular: 'Gemini voice config', plural: 'Gemini voice configs' },
            storage: this.geminiRealtimeStorage,
        },
    ];

    public providerGroups = this.llmLibraryService.providerGroups;
    public configs = this.llmConfigStorageService.configs;
    public searchQuery = signal('');
    public selectedCapability = signal<unknown>(null);
    public status = signal<LoadingState>(LoadingState.IDLE);
    public sectionErrors = signal<Record<SectionKey, boolean>>({
        llm: false,
        embedding: false,
        realtime: false,
        transcription: false,
        openai: false,
        elevenlabs: false,
        gemini: false,
        system_one: false,
    });

    public readonly selectMode = signal(false);
    public readonly selectedKeys = signal<ReadonlySet<string>>(new Set());
    public readonly isDeleting = signal(false);
    /** Count of items `deleteSelected` would actually send, i.e. ids that still resolve against
     *  the same sources it uses — not the raw `selectedKeys` size, which can include stale keys
     *  for items a preview already evicted (see F3). */
    public readonly selectedCount = computed(() => {
        const groups = llmLibraryBulkDeleteGroups(this.selectedKeys(), this.bulkDeleteSources());
        return groups.reduce((sum, group) => sum + group.items.length, 0);
    });

    readonly configTypeSections: { type: ModelTypes; label: string; key: SectionKey }[] = [
        { type: ModelTypes.LLM, label: 'LLM', key: 'llm' },
        { type: ModelTypes.EMBEDDING, label: 'Embedding', key: 'embedding' },
    ];

    filteredGroups = computed<LlmLibraryProviderGroup[]>(() => {
        const query = this.searchQuery().toLowerCase();
        const cap = this.selectedCapability() as string;

        return this.providerGroups()
            .map((group) => {
                const filteredModels = group.models.filter((model) => {
                    const matchesSearch =
                        !query ||
                        model.customName.toLowerCase().includes(query) ||
                        model.modelName.toLowerCase().includes(query) ||
                        group.providerName.toLowerCase().includes(query);

                    const matchesCap = cap === null || model.tags.some((t) => t.name.includes(cap));

                    return matchesSearch && matchesCap;
                });

                return { ...group, models: filteredModels };
            })
            .filter((group) => group.models.length > 0);
    });

    filteredVoiceProviders = computed(() => {
        const query = this.searchQuery().toLowerCase();
        const errors = this.sectionErrors();
        return this.voiceProviders
            .map((provider) => ({
                ...provider,
                hasError: errors[provider.key],
                cards: provider.storage
                    .configs()
                    .filter((c) => {
                        if (!query) return true;
                        return (
                            c.custom_name.toLowerCase().includes(query) ||
                            c.model_name.toLowerCase().includes(query) ||
                            provider.label.toLowerCase().includes(query)
                        );
                    })
                    .map((config) => ({ config, model: toVoiceCardModel(config) })),
            }))
            .filter((provider) => provider.hasError || provider.cards.length > 0);
    });

    filteredSystemOne = computed(() => {
        const query = this.searchQuery().toLowerCase();
        const llmConfigNames = new Map(
            this.llmConfigStorageService.configs().map((config) => [config.id, config.custom_name])
        );
        const hasError = this.sectionErrors().system_one;
        const cards = this.systemOneStorage
            .configs()
            .map((config) => ({
                config,
                model: toSystemOneCardModel(
                    config,
                    config.llm_config === null ? undefined : llmConfigNames.get(config.llm_config)
                ),
            }))
            .filter(
                ({ model }) =>
                    !query ||
                    model.customName.toLowerCase().includes(query) ||
                    model.modelName.toLowerCase().includes(query) ||
                    SYSTEM_ONE_LABEL.toLowerCase().includes(query)
            );
        return { hasError, cards, isVisible: hasError || cards.length > 0 };
    });

    groupedByType = computed(() => {
        const all = this.filteredGroups();
        const errors = this.sectionErrors();
        return this.configTypeSections
            .map((section) => ({
                ...section,
                hasError: errors[section.key],
                groups: all
                    .filter((g) => g.configType === section.type)
                    .sort((a, b) => a.providerName.localeCompare(b.providerName)),
            }))
            .filter((section) => section.hasError || section.groups.length > 0);
    });

    hasNoConfigs = computed(
        () =>
            this.groupedByType().length === 0 &&
            this.filteredVoiceProviders().length === 0 &&
            !this.filteredSystemOne().isVisible
    );

    public capabilities = computed<SelectItem[]>(() => [
        { name: 'All Capabilities', value: null },
        ...this.configs().flatMap((config) => config.tags.map((tag) => ({ name: tag.name, value: tag.name }))),
    ]);

    /** Keys of every card currently rendered (not hidden behind a section/provider error). */
    private readonly visibleSelectionKeys = computed<ReadonlySet<string>>(() => {
        const keys = new Set<string>();
        for (const section of this.groupedByType()) {
            if (section.hasError) continue;
            for (const group of section.groups) {
                for (const model of group.models) {
                    keys.add(llmLibrarySelectionKey(this.kindForModel(model), model.id));
                }
            }
        }
        for (const provider of this.filteredVoiceProviders()) {
            if (provider.hasError) continue;
            for (const card of provider.cards) {
                keys.add(llmLibrarySelectionKey(provider.key, card.config.id));
            }
        }
        const systemOne = this.filteredSystemOne();
        if (!systemOne.hasError) {
            for (const card of systemOne.cards) {
                keys.add(llmLibrarySelectionKey('system_one', card.config.id));
            }
        }
        return keys;
    });

    public readonly allVisibleSelected = computed(() => {
        const visible = this.visibleSelectionKeys();
        if (visible.size === 0) return false;
        const selected = this.selectedKeys();
        return [...visible].every((key) => selected.has(key));
    });

    private readonly bulkDeleteSources = computed<Record<LlmLibrarySelectionKind, LlmLibraryBulkDeleteSource>>(() => {
        const sources: Record<LlmLibrarySelectionKind, LlmLibraryBulkDeleteSource> = {
            llm: {
                label: LLM_BULK_DELETE_LABEL,
                target: this.llmConfigStorageService,
                configs: this.llmConfigStorageService.configs(),
            },
            embedding: {
                label: EMBEDDING_BULK_DELETE_LABEL,
                target: this.embeddingConfigStorage,
                configs: this.embeddingConfigStorage.configs(),
            },
            openai: this.voiceProviderSource('openai'),
            elevenlabs: this.voiceProviderSource('elevenlabs'),
            gemini: this.voiceProviderSource('gemini'),
            system_one: {
                label: SYSTEM_ONE_BULK_DELETE_LABEL,
                target: this.systemOneStorage,
                configs: this.systemOneStorage.configs(),
            },
        };
        return sources;
    });

    ngOnInit() {
        this.linkedConfigParams = takeQueryParams(this.route, this.router, ['configType', 'configId']);
        this.loadAll();
    }

    public retrySection(key: SectionKey): void {
        this.sourceFor(key)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.sectionErrors.update((e) => ({ ...e, [key]: false })),
                error: () => this.sectionErrors.update((e) => ({ ...e, [key]: true })),
            });
    }

    private sourceFor(key: SectionKey): Observable<unknown> {
        switch (key) {
            case 'llm':
                return this.llmLibraryService.loadLlmData();
            case 'embedding':
                return this.llmLibraryService.loadEmbeddingData();
            case 'realtime':
                return this.llmLibraryService.loadRealtimeData();
            case 'transcription':
                return this.llmLibraryService.loadTranscriptionData();
            case 'system_one':
                return this.systemOneStorage.getAllConfigs();
            default:
                return this.voiceProviders.find((p) => p.key === key)!.storage.getAllConfigs();
        }
    }

    private loadAll(): void {
        this.status.set(LoadingState.LOADING);

        const keys: SectionKey[] = [
            'llm',
            'embedding',
            'realtime',
            'transcription',
            ...this.voiceProviders.map((p) => p.key),
            'system_one',
        ];
        const errors: Record<SectionKey, boolean> = {
            llm: false,
            embedding: false,
            realtime: false,
            transcription: false,
            openai: false,
            elevenlabs: false,
            gemini: false,
            system_one: false,
        };

        const tracked = keys.map((key) =>
            this.sourceFor(key).pipe(
                catchError(() => {
                    errors[key] = true;
                    return of(null);
                })
            )
        );

        forkJoin(tracked)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => {
                this.sectionErrors.set(errors);
                this.status.set(LoadingState.LOADED);
                this.openLinkedConfig();
            });
    }

    /**
     * `?configType=&configId=` opens that config as its Edit button does. A viewer without that button gets the library
     * searched for it instead. An unknown config is ignored.
     */
    private openLinkedConfig(): void {
        const { configType, configId } = this.linkedConfigParams;
        this.linkedConfigParams = {};
        if (configType == null || configId == null) return;
        const linked = this.findLinkedConfig(configType, Number(configId));
        if (!linked) return;
        if (this.permissions.can(ResourceCode.LlmConfigs, ActionCode.Update)) linked.open();
        else this.searchQuery.set(linked.name);
    }

    private findLinkedConfig(configType: string, id: number): LinkedConfig | null {
        const voiceProviderKey = VOICE_CONFIG_TYPES.get(configType);
        if (voiceProviderKey) {
            const provider = this.voiceProviders.find((candidate) => candidate.key === voiceProviderKey);
            const config = provider?.storage.configs().find((candidate) => candidate.id === id);
            return provider && config
                ? { name: config.custom_name, open: () => this.onEditConfig(provider, config) }
                : null;
        }
        if (configType === 'system-one') {
            const config = this.systemOneStorage.configs().find((candidate) => candidate.id === id);
            return config ? { name: config.custom_name, open: () => this.onEditSystemOne(config) } : null;
        }
        const modelType = MODEL_CONFIG_TYPES.get(configType);
        if (!modelType) return null;
        const model = this.providerGroups()
            .flatMap((group) => group.models)
            .find((candidate) => candidate.configType === modelType && candidate.id === id);
        return model ? { name: model.customName, open: () => this.onEdit(model) } : null;
    }

    onEditConfig(provider: VoiceProvider, config: RealtimeConfig): void {
        const data: RealtimeConfigDialogData = { config: config, provider: provider.key };
        this.dialog.open(RealtimeConfigDialogComponent, {
            height: '90vh',
            width: '600px',
            disableClose: true,
            data,
        });
    }

    /** Opens the same details the LLM and embedding cards show; the dialog closes back to `trigger`. */
    onViewConfigDetails(config: RealtimeConfig, trigger: HTMLElement): void {
        this.authorshipDetailsDialog.open('Configuration Details', config, trigger);
    }

    onDeleteConfig(provider: VoiceProvider, config: RealtimeConfig): void {
        const group: BulkDeleteGroup = {
            target: provider.storage,
            label: provider.deleteLabel,
            items: [{ id: config.id, name: config.custom_name }],
        };

        this.bulkDeleteService
            .run([group])
            .pipe(
                tap((outcomes) => this.applyDefaultModelsOutdated(outcomes)),
                tap(() => this.focusAddAfterDelete()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    onEditSystemOne(config: SystemOneConfig): void {
        const data: SystemOneConfigDialogData = { config };
        this.dialog.open(SystemOneConfigDialogComponent, {
            height: '90vh',
            width: '600px',
            disableClose: true,
            data,
        });
    }

    onViewSystemOneDetails(config: SystemOneConfig, trigger: HTMLElement): void {
        this.authorshipDetailsDialog.open('Configuration Details', config, trigger);
    }

    onDeleteSystemOne(config: SystemOneConfig): void {
        const group: BulkDeleteGroup = {
            target: this.systemOneStorage,
            label: SYSTEM_ONE_BULK_DELETE_LABEL,
            items: [{ id: config.id, name: config.custom_name }],
        };
        this.bulkDeleteService.run([group]).pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    public isSystemOneSelected(config: SystemOneConfig): boolean {
        return this.selectedKeys().has(llmLibrarySelectionKey('system_one', config.id));
    }

    public onSystemOneSelectedChange(config: SystemOneConfig, selected: boolean): void {
        if (this.isDeleting()) return;
        this.setSelected('system_one', config.id, selected);
    }

    public isVoiceSelected(provider: VoiceProvider, config: RealtimeConfig): boolean {
        return this.selectedKeys().has(llmLibrarySelectionKey(provider.key, config.id));
    }

    public onVoiceSelectedChange(provider: VoiceProvider, config: RealtimeConfig, selected: boolean): void {
        if (this.isDeleting()) return;
        this.setSelected(provider.key, config.id, selected);
    }

    public onSearchChange(value: string): void {
        this.searchQuery.set(value);
    }

    public onAddModel(): void {
        this.dialog.open(AddConfigurationDialogComponent, { autoFocus: false });
    }

    public onEdit(model: LlmLibraryModel): void {
        const dialogComponents: Partial<Record<ModelTypes, ComponentType<unknown>>> = {
            [ModelTypes.LLM]: LlmModelConfigDialogComponent,
            [ModelTypes.EMBEDDING]: EmbeddingModelConfigDialogComponent,
        };
        const component = dialogComponents[model.configType];
        if (!component) return;
        this.dialog.open(component, {
            height: '90vh',
            width: '600px',
            data: { configId: model.id },
        });
    }

    public onViewDetails({ model, trigger }: LlmLibraryCardViewDetailsEvent): void {
        const findDetails: Partial<Record<ModelTypes, () => AuthorshipDetailsSource | undefined>> = {
            [ModelTypes.LLM]: () => this.llmConfigStorageService.configs().find((config) => config.id === model.id),
            [ModelTypes.EMBEDDING]: () =>
                this.embeddingConfigStorage.configs().find((config) => config.id === model.id),
        };
        const details = findDetails[model.configType]?.();
        if (!details) return;
        this.authorshipDetailsDialog.open('Configuration Details', details, trigger);
    }

    public onDelete(model: LlmLibraryModel): void {
        this.bulkDeleteService
            .run([this.buildModelGroup(model)])
            .pipe(
                tap((outcomes) => this.applyDefaultModelsOutdated(outcomes)),
                tap(() => this.focusAddAfterDelete()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    public enterSelectMode(): void {
        this.selectMode.set(true);
    }

    public exitSelectMode(): void {
        this.selectMode.set(false);
        this.selectedKeys.set(new Set());
    }

    public toggleSelectAll(): void {
        this.selectedKeys.set(this.allVisibleSelected() ? new Set() : new Set(this.visibleSelectionKeys()));
    }

    public isModelSelected(model: LlmLibraryModel): boolean {
        return this.selectedKeys().has(llmLibrarySelectionKey(this.kindForModel(model), model.id));
    }

    public onCardSelectedChange(model: LlmLibraryModel, selected: boolean): void {
        if (this.isDeleting()) return;
        this.setSelected(this.kindForModel(model), model.id, selected);
    }

    public deleteSelected(): void {
        const groups = llmLibraryBulkDeleteGroups(this.selectedKeys(), this.bulkDeleteSources());
        if (groups.length === 0) return;

        this.isDeleting.set(true);
        this.bulkDeleteService
            .run(groups)
            .pipe(
                tap((outcomes) => {
                    this.applyDefaultModelsOutdated(outcomes);
                    this.exitSelectMode();
                    this.focusAddAfterDelete();
                }),
                finalize(() => this.isDeleting.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    protected readonly systemOneLabel = SYSTEM_ONE_LABEL;
    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;

    /** The deleted card (or the bulk Delete button, gone with select mode) had the focus: it goes to Add Configuration. */
    private focusAddAfterDelete(): void {
        afterNextRender(() => this.addButton()?.focus(), { injector: this.injector });
    }

    private kindForModel(model: LlmLibraryModel): LlmLibrarySelectionKind {
        return model.configType === ModelTypes.EMBEDDING ? 'embedding' : 'llm';
    }

    private voiceProviderSource(key: RealtimeProvider): LlmLibraryBulkDeleteSource {
        const provider = this.voiceProviders.find((candidate) => candidate.key === key)!;
        return { label: provider.deleteLabel, target: provider.storage, configs: provider.storage.configs() };
    }

    private buildModelGroup(model: LlmLibraryModel): BulkDeleteGroup {
        const source = this.bulkDeleteSources()[this.kindForModel(model)];
        return { target: source.target, label: source.label, items: [{ id: model.id, name: model.customName }] };
    }

    private setSelected(kind: LlmLibrarySelectionKind, id: number, selected: boolean): void {
        const key = llmLibrarySelectionKey(kind, id);
        const next = new Set(this.selectedKeys());
        if (selected) {
            next.add(key);
        } else {
            next.delete(key);
        }
        this.selectedKeys.set(next);
    }

    private applyDefaultModelsOutdated(outcomes: BulkDeleteOutcome[]): void {
        const hasDefaultModelChange = outcomes.some(
            (outcome) =>
                (outcome.group.target === this.llmConfigStorageService ||
                    outcome.group.target === this.embeddingConfigStorage) &&
                (outcome.response?.deleted_count ?? 0) > 0
        );
        if (hasDefaultModelChange) {
            this.defaultModelsStorageService.markDefaultModelsOutdated();
        }
        // The server clears the LLM link of a System One config whose LLM config was deleted.
        const deletedLlmConfig = outcomes.some(
            (outcome) =>
                outcome.group.target === this.llmConfigStorageService && (outcome.response?.deleted_count ?? 0) > 0
        );
        if (deletedLlmConfig) {
            this.systemOneStorage
                .getAllConfigs(true)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    error: () => {},
                });
        }
    }
}
