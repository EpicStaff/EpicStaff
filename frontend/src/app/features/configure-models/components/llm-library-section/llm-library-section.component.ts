import { Dialog } from '@angular/cdk/dialog';
import { OverlayContainer } from '@angular/cdk/overlay';
import { ComponentType } from '@angular/cdk/portal';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    Injector,
    OnInit,
    Signal,
    signal,
    untracked,
    viewChild,
    viewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
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
import { forkJoin, Observable, of } from 'rxjs';
import { catchError, finalize, tap } from 'rxjs/operators';

import { LoadingState } from '../../../../core/enums/loading-state.enum';
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

const SYSTEM_ONE_LABEL = 'System One Configs';
const LLM_BULK_DELETE_LABEL: BulkDeleteLabel = { singular: 'LLM config', plural: 'LLM configs' };
const EMBEDDING_BULK_DELETE_LABEL: BulkDeleteLabel = { singular: 'embedding config', plural: 'embedding configs' };
const SYSTEM_ONE_BULK_DELETE_LABEL: BulkDeleteLabel = { singular: 'System One config', plural: 'System One configs' };
/** Design minimums while the toolbar sits beside the title, and the gaps (title to toolbar, between controls). */
const TITLE_MIN_WIDTH = 372;
const SEARCH_MIN_WIDTH = 201;
const HEADER_GAP = 24;
const CONTROL_GAP = 8;

/** A toolbar control (after the search) in one of its looks; the action is Add, or Delete with a selection. */
type ToolbarControlLook =
    | 'capabilities'
    | 'capabilities-icon'
    | 'select'
    | 'select-icon'
    | 'selected'
    | 'selected-icon'
    | 'add'
    | 'add-icon'
    | 'delete'
    | 'delete-icon';

/**
 * Widths of each look until it has been on screen once and measured: the icon looks are the design's fixed sizes,
 * the labelled ones estimates for Inter 14px.
 */
const ESTIMATED_CONTROL_WIDTHS: Record<ToolbarControlLook, number> = {
    capabilities: 163,
    'capabilities-icon': 67,
    select: 96,
    'select-icon': 40,
    selected: 177,
    'selected-icon': 131,
    add: 180,
    'add-icon': 40,
    delete: 120,
    'delete-icon': 40,
};

/**
 * Beside the title with labels; beside it icon-only; or under it (`stacked`), its second row giving up labels from
 * the end: first the action (Add or Delete) goes icon-only, then all of them.
 */
type ToolbarLayout = 'labels' | 'icons' | 'stacked' | 'stacked-action-icon' | 'stacked-icons';

interface ToolbarIcons {
    capabilities: boolean;
    select: boolean;
    action: boolean;
}

interface ToolbarControlLooks {
    capabilities: ToolbarControlLook;
    select: ToolbarControlLook;
    action: ToolbarControlLook;
}

const ALL_LABELS: ToolbarIcons = { capabilities: false, select: false, action: false };
const ALL_ICONS: ToolbarIcons = { capabilities: true, select: true, action: true };
const ACTION_ICON: ToolbarIcons = { capabilities: false, select: false, action: true };

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
    host: {
        '(document:click)': 'onDocumentClick($event)',
        '(document:keydown.escape)': 'onDocumentEscape($event)',
    },
})
export class LlmLibrarySectionComponent implements OnInit {
    private readonly addButton = viewChild('addButton', { read: ButtonComponent });
    private readonly header = viewChild<ElementRef<HTMLElement>>('header');
    private readonly capabilitiesControl = viewChild<ElementRef<HTMLElement>>('capabilitiesControl');
    private readonly selectControl = viewChild(BulkSelectDropdownComponent, { read: ElementRef });
    private readonly actionControl = viewChild<ButtonComponent, ElementRef<HTMLElement>>('actionControl', {
        read: ElementRef,
    });
    private readonly bulkSelect = viewChild(BulkSelectDropdownComponent);
    private readonly bulkSelectElement = viewChild(BulkSelectDropdownComponent, { read: ElementRef });
    private readonly cardElements = viewChildren(LlmLibraryCardComponent, { read: ElementRef });

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
    private readonly overlayContainer = inject(OverlayContainer);

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
    /** Delete replaces Add Configuration, and Select shows its count, only while something is selected. */
    public readonly hasSelection = computed(() => this.selectedCount() > 0);
    /** Select mode with nothing ticked yet: a click outside the cards or Escape leaves it. */
    private readonly isSelectModeEmpty = computed(() => this.selectMode() && !this.hasSelection());
    /** Null until measured: the first frame keeps the labels in the row. */
    private readonly headerWidth = signal<number | null>(null);
    /** Natural width of each control look, taken while it was on screen; estimates until then. */
    private readonly controlWidths = signal<Partial<Record<ToolbarControlLook, number>>>({});
    /**
     * Every switch comes from the measured widths and the design's numbers: the labelled toolbar beside a 372px title
     * (search at 201px), else the icon-only one, else under the title with as many labels as its row fits.
     */
    protected readonly toolbarLayout = computed<ToolbarLayout>(() => {
        const width = this.headerWidth();
        if (width === null) return 'labels';
        const besideTitle = width - TITLE_MIN_WIDTH - HEADER_GAP;
        if (this.toolbarRowWidth(ALL_LABELS) <= besideTitle) return 'labels';
        if (this.toolbarRowWidth(ALL_ICONS) <= besideTitle) return 'icons';
        if (this.controlsRowWidth(ALL_LABELS) <= width) return 'stacked';
        if (this.controlsRowWidth(ACTION_ICON) <= width) return 'stacked-action-icon';
        return 'stacked-icons';
    });
    protected readonly isStacked = computed(() => this.toolbarLayout().startsWith('stacked'));
    protected readonly toolbarIcons = computed<ToolbarIcons>(() => {
        switch (this.toolbarLayout()) {
            case 'icons':
            case 'stacked-icons':
                return ALL_ICONS;
            case 'stacked-action-icon':
                return ACTION_ICON;
            default:
                return ALL_LABELS;
        }
    });
    /** Beside the title, what the toolbar needs: the title gives way (to its 372px minimum) before it does. */
    protected readonly toolbarMinWidth = computed(() =>
        this.isStacked() ? null : this.toolbarRowWidth(this.toolbarIcons())
    );

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
        { name: 'All capabilities', value: null },
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

    private readonly resizeObserver =
        typeof ResizeObserver === 'undefined' ? null : new ResizeObserver((entries) => this.onResize(entries));
    private observedElements: HTMLElement[] = [];
    /** The header and the toolbar controls on screen, observed as they come and go. */
    private readonly observeToolbar = effect(() => {
        const elements = [this.header(), this.capabilitiesControl(), this.selectControl(), this.actionControl()]
            .filter((element): element is ElementRef<HTMLElement> => !!element)
            .map((element) => element.nativeElement);
        untracked(() => {
            for (const element of this.observedElements) {
                if (!elements.includes(element)) this.resizeObserver?.unobserve(element);
            }
            for (const element of elements) this.resizeObserver?.observe(element);
            this.observedElements = elements;
        });
    });

    constructor() {
        this.destroyRef.onDestroy(() => this.resizeObserver?.disconnect());
    }

    ngOnInit() {
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
            });
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

    /** Clears the selection and stays in select mode; the × (`exitSelectMode`) leaves it too. */
    public clearSelection(): void {
        this.selectedKeys.set(new Set());
    }

    /**
     * Leaves an empty select mode on a click outside the cards and the Select control. Clicks in overlays (the
     * capabilities panel, a card menu, dialogs, tooltips) leave it alone: they belong to what is open above the page.
     * A target already gone from the page (a control the click itself swapped) says nothing about where it landed.
     */
    public onDocumentClick(event: MouseEvent): void {
        if (!this.isSelectModeEmpty()) return;
        const target = event.target;
        if (!(target instanceof Node) || !target.isConnected) return;
        if (this.overlayContainer.getContainerElement().contains(target)) return;
        if (this.bulkSelectElement()?.nativeElement.contains(target)) return;
        if (this.cardElements().some((card) => card.nativeElement.contains(target))) return;
        this.exitSelectMode();
    }

    /** Escape leaves an empty select mode, unless something above the page (a menu, a dialog) takes it. */
    public onDocumentEscape(event: Event): void {
        if (!this.isSelectModeEmpty() || event.defaultPrevented) return;
        const target = event.target;
        if (target instanceof Node && this.overlayContainer.getContainerElement().contains(target)) return;
        this.exitSelectMode();
        // The card checkboxes that may have had the focus are gone with select mode.
        this.bulkSelect()?.focus();
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

    /** Unticking the last selected card ends select mode; entering it from the Select menu starts at 0 and stays. */
    private setSelected(kind: LlmLibrarySelectionKind, id: number, selected: boolean): void {
        const key = llmLibrarySelectionKey(kind, id);
        const next = new Set(this.selectedKeys());
        if (selected) {
            next.add(key);
        } else {
            next.delete(key);
        }
        this.selectedKeys.set(next);
        if (!selected && this.selectedCount() === 0) {
            this.exitSelectMode();
        }
    }

    /**
     * The header's own width (not the viewport's: the sidebar and the settings layout around it do not matter), and
     * each control's natural width in the look it shows. Controls are recorded against the looks they were rendered
     * with, before a new header width can change those looks.
     */
    private onResize(entries: ResizeObserverEntry[]): void {
        const looks = this.controlLooks(this.toolbarIcons());
        const measured: Partial<Record<ToolbarControlLook, number>> = {};
        let headerWidth: number | null = null;
        for (const entry of entries) {
            const target = entry.target;
            if (target === this.header()?.nativeElement) {
                headerWidth = entry.contentRect.width;
                continue;
            }
            const width = entry.borderBoxSize?.[0]?.inlineSize ?? target.getBoundingClientRect().width;
            if (width <= 0) continue;
            if (target === this.capabilitiesControl()?.nativeElement) measured[looks.capabilities] = width;
            else if (target === this.selectControl()?.nativeElement) measured[looks.select] = width;
            else if (target === this.actionControl()?.nativeElement) measured[looks.action] = width;
        }
        if (Object.keys(measured).length > 0) this.controlWidths.update((widths) => ({ ...widths, ...measured }));
        if (headerWidth !== null) this.headerWidth.set(headerWidth);
    }

    private controlLooks(icons: ToolbarIcons): ToolbarControlLooks {
        const selection = this.hasSelection();
        const selectLook: ToolbarControlLook = selection ? 'selected' : 'select';
        const actionLook: ToolbarControlLook = selection ? 'delete' : 'add';
        return {
            capabilities: icons.capabilities ? 'capabilities-icon' : 'capabilities',
            select: icons.select ? `${selectLook}-icon` : selectLook,
            action: icons.action ? `${actionLook}-icon` : actionLook,
        } as ToolbarControlLooks;
    }

    /** The controls after the search, in the given looks, with the gaps between them; absent ones count nothing. */
    private controlsRowWidth(icons: ToolbarIcons): number {
        const looks = this.controlLooks(icons);
        const widths = this.controlWidths();
        const present: ToolbarControlLook[] = [looks.capabilities];
        if (this.selectControl()) present.push(looks.select);
        if (this.actionControl()) present.push(looks.action);
        const total = present.reduce((sum, look) => sum + (widths[look] ?? ESTIMATED_CONTROL_WIDTHS[look]), 0);
        return total + CONTROL_GAP * (present.length - 1);
    }

    /** The whole toolbar beside the title: the search at its minimum, then the controls. */
    private toolbarRowWidth(icons: ToolbarIcons): number {
        return SEARCH_MIN_WIDTH + CONTROL_GAP + this.controlsRowWidth(icons);
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
