import { Dialog } from '@angular/cdk/dialog';
import { OverlayContainer } from '@angular/cdk/overlay';
import { ComponentType } from '@angular/cdk/portal';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    DOCUMENT,
    effect,
    ElementRef,
    inject,
    Injector,
    OnInit,
    signal,
    untracked,
    viewChild,
    viewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import {
    AppSvgIconComponent,
    AuthorshipDetailsDialogService,
    AuthorshipDetailsSource,
    CheckboxComponent,
    EmbeddingModelConfigDialogComponent,
    FetchErrorStateComponent,
    LlmModelConfigDialogComponent,
    LoadingSpinnerComponent,
} from '@shared/components';
import { PROVIDER_ICON_PATHS } from '@shared/constants';
import {
    ActionCode,
    BulkDeleteGroup,
    BulkDeleteLabel,
    BulkDeleteOutcome,
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
import { getProviderHeadingIcon, getProviderIconPath, providerDisplayName, takeQueryParams } from '@shared/utils';
import { forkJoin, Observable, of } from 'rxjs';
import { catchError, finalize, tap } from 'rxjs/operators';

import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { SYSTEM_ONE_LABEL } from '../../constants/llm-library-capabilities.constant';
import { SYSTEM_ONE_PROVIDERS } from '../../constants/system-one-providers.constant';
import {
    LibraryCard,
    LibraryLoadKey,
    LibraryProviderGroup,
    LibrarySection,
    LibrarySectionError,
    LibrarySectionKey,
    VoiceProvider,
} from '../../models/llm-library.model';
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
import {
    compareProviderCreationOrder,
    LLM_LIBRARY_CARD_GAP,
    llmLibraryCardsPerRow,
    packLlmLibraryRows,
    providerCreationOrder,
} from '../../utils/llm-library-layout.util';
import { AddConfigurationDialogComponent } from '../add-configuration-dialog/add-configuration-dialog.component';
import {
    LlmLibraryCardComponent,
    LlmLibraryCardViewDetailsEvent,
} from '../llm-library-card/llm-library-card.component';
import { LlmLibraryHeaderComponent } from '../llm-library-header/llm-library-header.component';
import {
    RealtimeConfigDialogComponent,
    RealtimeConfigDialogData,
} from '../realtime-config-dialog/realtime-config-dialog.component';
import { RealtimeConfig, RealtimeProvider } from '../realtime-config-form/realtime-config-form.component';
import {
    SystemOneConfigDialogComponent,
    SystemOneConfigDialogData,
} from '../system-one-config-dialog/system-one-config-dialog.component';

/** Realtime (voice) configs have no tags, temperature or deprecation, so the shared card shows only their names. */
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

/** No load has failed: a fresh record each time, since a load fills its own in as its sources fail. */
function noLoadErrors(): Record<LibraryLoadKey, boolean> {
    return {
        llm: false,
        embedding: false,
        realtime: false,
        transcription: false,
        openai: false,
        elevenlabs: false,
        gemini: false,
        system_one: false,
    };
}

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

const LLM_BULK_DELETE_LABEL: BulkDeleteLabel = { singular: 'LLM config', plural: 'LLM configs' };
const EMBEDDING_BULK_DELETE_LABEL: BulkDeleteLabel = { singular: 'embedding config', plural: 'embedding configs' };
const SYSTEM_ONE_BULK_DELETE_LABEL: BulkDeleteLabel = { singular: 'System One config', plural: 'System One configs' };

@Component({
    selector: 'app-llm-library-section',
    imports: [
        FormsModule,
        LlmLibraryCardComponent,
        LlmLibraryHeaderComponent,
        AppSvgIconComponent,
        LoadingSpinnerComponent,
        FetchErrorStateComponent,
        CheckboxComponent,
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
    private readonly header = viewChild.required(LlmLibraryHeaderComponent);
    private readonly libraryElement = viewChild<ElementRef<HTMLElement>>('library');
    private readonly sectionsElement = viewChild<ElementRef<HTMLElement>>('sectionList');
    private readonly cardElements = viewChildren(LlmLibraryCardComponent, { read: ElementRef });
    private readonly sectionHeaders = viewChildren<ElementRef<HTMLElement>>('sectionHeader');

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
    private readonly overlayContainer = inject(OverlayContainer);
    private readonly document = inject(DOCUMENT);

    readonly voiceProviders: VoiceProvider[] = [
        {
            key: 'openai',
            name: 'OpenAI',
            deleteLabel: { singular: 'OpenAI realtime config', plural: 'OpenAI realtime configs' },
            storage: this.openaiRealtimeStorage,
        },
        {
            key: 'elevenlabs',
            name: 'ElevenLabs',
            deleteLabel: { singular: 'ElevenLabs realtime config', plural: 'ElevenLabs realtime configs' },
            storage: this.elevenLabsRealtimeStorage,
        },
        {
            key: 'gemini',
            name: 'Gemini',
            deleteLabel: { singular: 'Gemini realtime config', plural: 'Gemini realtime configs' },
            storage: this.geminiRealtimeStorage,
        },
    ];

    public providerGroups = this.llmLibraryService.providerGroups;
    public searchQuery = signal('');
    /** The section the Capabilities filter shows; null shows all of them. */
    public readonly selectedSectionFilter = signal<LibrarySectionKey | null>(null);
    public status = signal<LoadingState>(LoadingState.IDLE);
    public sectionErrors = signal<Record<LibraryLoadKey, boolean>>(noLoadErrors());

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
    public readonly hasSelection = computed(() => this.selectedCount() > 0);
    /** Select mode with nothing ticked yet: a click outside the cards or Escape leaves it. */
    private readonly isSelectModeEmpty = computed(() => this.selectMode() && !this.hasSelection());
    /**
     * Null until measured. The page's own width, which the sections span: measured on the page rather than on the
     * section list, which is not there while loading, so the first cards already get the right count per row.
     */
    private readonly libraryWidth = signal<number | null>(null);

    readonly configTypeSections: { type: ModelTypes; title: string; errorLabel: string; key: 'llm' | 'embedding' }[] = [
        { type: ModelTypes.LLM, title: 'LLM', errorLabel: 'LLM', key: 'llm' },
        { type: ModelTypes.EMBEDDING, title: 'Embeddings', errorLabel: 'Embedding', key: 'embedding' },
    ];

    /** Cards a row holds at the sections' width. */
    protected readonly cardsPerRow = computed(() => llmLibraryCardsPerRow(this.libraryWidth()));

    /** Every section with a card or an error to show, before the Capabilities filter and the search. */
    private readonly unfilteredSections = computed(() => this.buildSections(''));

    /** The sections the search and the Capabilities filter leave. */
    protected readonly sections = computed<LibrarySection[]>(() => {
        const shown = this.selectedSectionFilter();
        return this.buildSections(this.searchQuery().toLowerCase()).filter(
            (section) => shown === null || section.key === shown
        );
    });

    /** Sections collapsed by the user; all start open, and the state lasts as long as the page. */
    protected readonly collapsedSections = signal<ReadonlySet<LibrarySectionKey>>(new Set());

    /** Nothing to show at all; the search or the filter hiding every section is `hasNoMatches`. */
    protected readonly hasNoConfigs = computed(() => this.unfilteredSections().length === 0);
    protected readonly hasNoMatches = computed(() => !this.hasNoConfigs() && this.sections().length === 0);

    /** Keys of every card currently rendered (not hidden behind a section/provider error), collapsed or not. */
    private readonly visibleSelectionKeys = computed<ReadonlySet<string>>(
        () => new Set(this.sections().flatMap((section) => section.selectionKeys))
    );

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
        typeof ResizeObserver === 'undefined'
            ? null
            : new ResizeObserver((entries) => this.libraryWidth.set(entries[entries.length - 1].contentRect.width));
    /**
     * A selection never outlives its cards' visibility: a card the filter, the search or a load error hides is
     * neither counted nor deleted. Collapsed sections still count as shown. Dropping the last ticked card ends
     * select mode, as unticking it does.
     */
    private readonly pruneHiddenSelection = effect(() => {
        const visible = this.visibleSelectionKeys();
        untracked(() => {
            const selected = this.selectedKeys();
            const kept = new Set([...selected].filter((key) => visible.has(key)));
            if (kept.size === selected.size) return;
            this.selectedKeys.set(kept);
            if (this.selectedCount() === 0) this.exitSelectMode();
        });
    });
    /** The page's width, for the cards per row: its element is there from the first render on. */
    private readonly observeLibrary = effect(() => {
        const element = this.libraryElement()?.nativeElement;
        if (element) untracked(() => this.resizeObserver?.observe(element));
    });

    protected readonly cardGap = LLM_LIBRARY_CARD_GAP;

    constructor() {
        this.destroyRef.onDestroy(() => this.resizeObserver?.disconnect());
    }

    ngOnInit() {
        this.linkedConfigParams = takeQueryParams(this.route, this.router, ['configType', 'configId']);
        this.loadAll();
    }

    protected retrySection(key: LibraryLoadKey): void {
        this.sourceFor(key)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.sectionErrors.update((e) => ({ ...e, [key]: false })),
                error: () => this.sectionErrors.update((e) => ({ ...e, [key]: true })),
            });
    }

    private sourceFor(key: LibraryLoadKey): Observable<unknown> {
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

        const keys: LibraryLoadKey[] = [
            'llm',
            'embedding',
            'realtime',
            'transcription',
            ...this.voiceProviders.map((p) => p.key),
            'system_one',
        ];
        const errors = noLoadErrors();

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

    protected toggleSection(key: LibrarySectionKey): void {
        this.collapsedSections.update((collapsed) => {
            const next = new Set(collapsed);
            if (!next.delete(key)) next.add(key);
            return next;
        });
    }

    /** How many of the section's cards are ticked. */
    protected tickedCount(section: LibrarySection): number {
        const selected = this.selectedKeys();
        return section.selectionKeys.filter((key) => selected.has(key)).length;
    }

    /**
     * The section's box ticks all its cards when none is ticked, and unticks them all otherwise. The box is set to
     * match, since a click on a "-" box ticks it in the browser while it should clear.
     */
    protected onSectionCheckboxChange(section: LibrarySection, checkbox: CheckboxComponent): void {
        if (this.isDeleting()) return;
        const tickAll = this.tickedCount(section) === 0;
        checkbox.checked.set(tickAll);
        const next = new Set(this.selectedKeys());
        for (const key of section.selectionKeys) {
            if (tickAll) {
                next.add(key);
            } else {
                next.delete(key);
            }
        }
        this.selectedKeys.set(next);
        if (!tickAll && this.selectedCount() === 0) {
            this.exitSelectMode();
        }
    }

    protected onSearchChange(value: string): void {
        this.searchQuery.set(value);
    }

    protected onSectionFilterChange(value: LibrarySectionKey | null): void {
        this.selectedSectionFilter.set(value);
    }

    protected onAddModel(): void {
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

    protected enterSelectMode(): void {
        this.selectMode.set(true);
    }

    protected exitSelectMode(): void {
        this.selectMode.set(false);
        this.selectedKeys.set(new Set());
    }

    /** Clears the selection and stays in select mode; the × (`exitSelectMode`) leaves it too. */
    protected clearSelection(): void {
        this.selectedKeys.set(new Set());
    }

    /**
     * Leaves an empty select mode on a click outside the cards and the Select control. Clicks in overlays (the
     * capabilities panel, a card menu, dialogs, tooltips) leave it alone: they belong to what is open above the page.
     * A target already gone from the page (a control the click itself swapped) says nothing about where it landed.
     */
    protected onDocumentClick(event: MouseEvent): void {
        if (!this.isSelectModeEmpty()) return;
        const target = event.target;
        if (!(target instanceof Node) || !target.isConnected) return;
        if (this.overlayContainer.getContainerElement().contains(target)) return;
        if (this.header().containsSelectControl(target)) return;
        if (this.cardElements().some((card) => card.nativeElement.contains(target))) return;
        // A section's box ticks its cards, and its heading only collapses it: neither is a click away.
        if (this.sectionHeaders().some((header) => header.nativeElement.contains(target))) return;
        this.exitSelectMode();
    }

    /**
     * Escape leaves an empty select mode, unless something above the page (a menu, a dialog) takes it. The focus
     * moves to Select only when it had none (on the body) or sat in the sections, whose checkboxes go with select
     * mode; pressed in the search or elsewhere in the toolbar, Escape leaves the focus where it is.
     */
    protected onDocumentEscape(event: Event): void {
        if (!this.isSelectModeEmpty() || event.defaultPrevented) return;
        const target = event.target;
        if (target instanceof Node && this.overlayContainer.getContainerElement().contains(target)) return;
        const focused = this.document.activeElement;
        const focusGoesAway =
            focused === null ||
            focused === this.document.body ||
            !!this.sectionsElement()?.nativeElement.contains(focused);
        this.exitSelectMode();
        if (focusGoesAway) this.header().focusSelect();
    }

    protected toggleSelectAll(): void {
        this.selectedKeys.set(this.allVisibleSelected() ? new Set() : new Set(this.visibleSelectionKeys()));
    }

    protected isCardSelected(card: LibraryCard): boolean {
        return this.selectedKeys().has(card.selectionKey);
    }

    protected onCardSelectedChange(card: LibraryCard, selected: boolean): void {
        if (this.isDeleting()) return;
        this.setSelected(card.kind, card.id, selected);
    }

    protected deleteSelected(): void {
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

    /** The deleted card (or the bulk Delete button, gone with select mode) had the focus: it goes to Add Configuration. */
    private focusAddAfterDelete(): void {
        afterNextRender(() => this.header().focusAddButton(), { injector: this.injector });
    }

    /**
     * LLM, Embeddings, Realtime and System One, each left out when it has no card and no error to show. `query`
     * (lower case, empty for all) narrows the cards by name, model or provider.
     */
    private buildSections(query: string): LibrarySection[] {
        const errors = this.sectionErrors();
        const cardsPerRow = this.cardsPerRow();
        const modelGroups = this.searchedModelGroups(query);
        const sections = this.configTypeSections.map(({ type, title, errorLabel, key }) => {
            if (errors[key]) {
                return this.buildSection(
                    key,
                    title,
                    [{ key, title: `Failed to load ${errorLabel} configurations` }],
                    [],
                    cardsPerRow
                );
            }
            const createdAt = this.configCreationTimes(type);
            const groups = modelGroups
                .filter((group) => group.configType === type)
                .map((group) => this.toModelGroup(group, createdAt));
            return this.buildSection(key, title, [], groups, cardsPerRow);
        });

        const voice = this.searchedVoiceProviders(query);
        sections.push(
            this.buildSection(
                'voice',
                'Realtime',
                voice
                    .filter(({ hasError }) => hasError)
                    .map(({ provider }) => ({
                        key: provider.key,
                        title: `Failed to load ${provider.name} realtime configurations`,
                    })),
                voice
                    .filter(({ hasError, configs }) => !hasError && configs.length > 0)
                    .map(({ provider, configs }) => this.toVoiceGroup(provider, configs)),
                cardsPerRow
            )
        );

        const systemOneHasError = errors.system_one;
        sections.push(
            this.buildSection(
                'system_one',
                SYSTEM_ONE_LABEL,
                systemOneHasError ? [{ key: 'system_one', title: 'Failed to load System One configurations' }] : [],
                systemOneHasError ? [] : this.toSystemOneGroups(this.searchedSystemOneCards(query)),
                cardsPerRow
            )
        );

        return sections.filter((section) => section.errors.length > 0 || section.selectionKeys.length > 0);
    }

    private searchedModelGroups(query: string): LlmLibraryProviderGroup[] {
        return this.providerGroups()
            .map((group) => ({
                ...group,
                models: group.models.filter(
                    (model) =>
                        !query ||
                        model.customName.toLowerCase().includes(query) ||
                        model.modelName.toLowerCase().includes(query) ||
                        group.providerName.toLowerCase().includes(query) ||
                        providerDisplayName(group.providerName).toLowerCase().includes(query)
                ),
            }))
            .filter((group) => group.models.length > 0);
    }

    private searchedVoiceProviders(
        query: string
    ): { provider: VoiceProvider; hasError: boolean; configs: RealtimeConfig[] }[] {
        const errors = this.sectionErrors();
        return this.voiceProviders.map((provider) => ({
            provider,
            hasError: errors[provider.key],
            configs: provider.storage
                .configs()
                .filter(
                    (config) =>
                        !query ||
                        config.custom_name.toLowerCase().includes(query) ||
                        config.model_name.toLowerCase().includes(query) ||
                        `${provider.name} realtime`.toLowerCase().includes(query)
                ),
        }));
    }

    private searchedSystemOneCards(query: string): { config: SystemOneConfig; model: LlmLibraryModel }[] {
        const llmConfigNames = new Map(
            this.llmConfigStorageService.configs().map((config) => [config.id, config.custom_name])
        );
        return this.systemOneStorage
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
    }

    /** Groups in the order their providers were added, packed into rows. */
    private buildSection(
        key: LibrarySectionKey,
        title: string,
        errors: LibrarySectionError[],
        groups: LibraryProviderGroup[],
        cardsPerRow: number
    ): LibrarySection {
        const ordered = [...groups].sort((first, second) => compareProviderCreationOrder(first.order, second.order));
        return {
            key,
            title,
            errors,
            rows: packLlmLibraryRows(ordered, (group) => group.cards.length, cardsPerRow),
            providerList: ordered.flatMap((group) => (group.name === null ? [] : [group.name])).join(', '),
            selectionKeys: ordered.flatMap((group) => group.cards.map((card) => card.selectionKey)),
        };
    }

    /** Creation time of each config of the type, by id (the library models do not carry it). */
    private configCreationTimes(type: ModelTypes): Map<number, string | null> {
        const configs: { id: number; created_at: string | null }[] =
            type === ModelTypes.EMBEDDING
                ? this.embeddingConfigStorage.configs()
                : this.llmConfigStorageService.configs();
        return new Map(configs.map((config) => [config.id, config.created_at]));
    }

    private toModelGroup(group: LlmLibraryProviderGroup, createdAt: Map<number, string | null>): LibraryProviderGroup {
        return {
            id: group.id,
            name: providerDisplayName(group.providerName),
            ...getProviderHeadingIcon(group.providerName, group.providerIconPath),
            order: providerCreationOrder(
                group.models.map((model) => ({ id: model.id, createdAt: createdAt.get(model.id) ?? null }))
            ),
            cards: group.models.map((model) => {
                const kind = this.kindForModel(model);
                return {
                    selectionKey: llmLibrarySelectionKey(kind, model.id),
                    kind,
                    id: model.id,
                    model,
                    edit: () => this.onEdit(model),
                    remove: () => this.onDelete(model),
                    viewDetails: (trigger: HTMLElement) => this.onViewDetails({ model, trigger }),
                };
            }),
        };
    }

    private toVoiceGroup(provider: VoiceProvider, configs: RealtimeConfig[]): LibraryProviderGroup {
        return {
            id: `voice-${provider.key}`,
            name: provider.name,
            ...getProviderHeadingIcon(
                provider.name,
                PROVIDER_ICON_PATHS[provider.key] ?? PROVIDER_ICON_PATHS['default']
            ),
            order: providerCreationOrder(configs.map((config) => ({ id: config.id, createdAt: config.created_at }))),
            cards: configs.map((config) => ({
                selectionKey: llmLibrarySelectionKey(provider.key, config.id),
                kind: provider.key,
                id: config.id,
                model: toVoiceCardModel(config),
                edit: () => this.onEditConfig(provider, config),
                remove: () => this.onDeleteConfig(provider, config),
                viewDetails: (trigger: HTMLElement) => this.onViewConfigDetails(config, trigger),
            })),
        };
    }

    /** One group per System One provider that has cards (TypeSafe, OpenAI, LLM), in the order they were added. */
    private toSystemOneGroups(cards: { config: SystemOneConfig; model: LlmLibraryModel }[]): LibraryProviderGroup[] {
        return SYSTEM_ONE_PROVIDERS.map((provider) => ({
            provider,
            providerCards: cards.filter(({ config }) => config.provider === provider.key),
        }))
            .filter(({ providerCards }) => providerCards.length > 0)
            .map(({ provider, providerCards }) => ({
                id: `system_one-${provider.key}`,
                name: provider.label,
                ...getProviderHeadingIcon(provider.key, getProviderIconPath(provider.key)),
                order: providerCreationOrder(
                    providerCards.map(({ config }) => ({ id: config.id, createdAt: config.created_at }))
                ),
                cards: providerCards.map(({ config, model }) => ({
                    selectionKey: llmLibrarySelectionKey('system_one', config.id),
                    kind: 'system_one',
                    id: config.id,
                    model,
                    edit: () => this.onEditSystemOne(config),
                    remove: () => this.onDeleteSystemOne(config),
                    viewDetails: (trigger: HTMLElement) => this.onViewSystemOneDetails(config, trigger),
                })),
            }));
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
