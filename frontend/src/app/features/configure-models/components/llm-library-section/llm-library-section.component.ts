import { Dialog } from '@angular/cdk/dialog';
import { ComponentType } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    OnInit,
    Signal,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import {
    AppSvgIconComponent,
    ConfirmationDialogData,
    ConfirmationDialogService,
    EmbeddingModelConfigDialogComponent,
    LlmModelConfigDialogComponent,
    LoadingSpinnerComponent,
    SelectComponent,
    SelectItem,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, LlmLibraryModel, LlmLibraryProviderGroup, ModelTypes, ResourceCode } from '@shared/models';
import { EmbeddingConfigStorageService, LlmConfigStorageService, LLMLibraryService } from '@shared/services';
import { Observable } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { DefaultModelsStorageService } from '../../services/default-models-storage.service';
import { ElevenLabsRealtimeConfigStorageService } from '../../services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../services/llms/openai-realtime-config-storage.service';
import { AddConfigurationDialogComponent } from '../add-configuration-dialog/add-configuration-dialog.component';
import { LlmLibraryCardComponent } from '../llm-library-card/llm-library-card.component';
import {
    RealtimeConfigDialogComponent,
    RealtimeProvider,
} from '../realtime-config-dialog/realtime-config-dialog.component';

interface VoiceProviderConfig {
    id: number;
    custom_name: string;
    model_name: string;
}

interface VoiceProvider {
    key: RealtimeProvider;
    label: string;
    storage: {
        configs: Signal<VoiceProviderConfig[]>;
        getAllConfigs(force?: boolean): Observable<unknown[]>;
        deleteConfig(id: number): Observable<void>;
    };
}

@Component({
    selector: 'app-llm-library-section',
    imports: [
        FormsModule,
        LlmLibraryCardComponent,
        AppSvgIconComponent,
        LoadingSpinnerComponent,
        SelectComponent,
        HasPermissionDirective,
    ],
    templateUrl: './llm-library-section.component.html',
    styleUrls: ['./llm-library-section.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmLibrarySectionComponent implements OnInit {
    private readonly llmLibraryService = inject(LLMLibraryService);
    private readonly llmConfigStorageService = inject(LlmConfigStorageService);
    private readonly embeddingConfigStorage = inject(EmbeddingConfigStorageService);
    private readonly openaiRealtimeStorage = inject(OpenAIRealtimeConfigStorageService);
    private readonly elevenLabsRealtimeStorage = inject(ElevenLabsRealtimeConfigStorageService);
    private readonly geminiRealtimeStorage = inject(GeminiRealtimeConfigStorageService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly defaultModelsStorageService = inject(DefaultModelsStorageService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly dialog = inject(Dialog);
    private readonly toast = inject(ToastService);

    readonly voiceProviders: VoiceProvider[] = [
        { key: 'openai', label: 'OpenAI Voice Configs', storage: this.openaiRealtimeStorage },
        { key: 'elevenlabs', label: 'ElevenLabs Voice Configs', storage: this.elevenLabsRealtimeStorage },
        { key: 'gemini', label: 'Gemini Voice Configs', storage: this.geminiRealtimeStorage },
    ];

    public providerGroups = this.llmLibraryService.providerGroups;
    public configs = this.llmConfigStorageService.configs;
    public searchQuery = signal('');
    public selectedCapability = signal<unknown>(null);
    public configsLoaded = signal<boolean>(false);

    readonly configTypeSections: { type: ModelTypes; label: string }[] = [
        { type: ModelTypes.LLM, label: 'LLM' },
        { type: ModelTypes.EMBEDDING, label: 'Embedding' },
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
        return this.voiceProviders.map((provider) => ({
            ...provider,
            configs: provider.storage.configs().filter((c) => {
                if (!query) return true;
                return (
                    c.custom_name.toLowerCase().includes(query) ||
                    c.model_name.toLowerCase().includes(query) ||
                    provider.label.toLowerCase().includes(query)
                );
            }),
        }));
    });

    groupedByType = computed(() => {
        const all = this.filteredGroups();
        return this.configTypeSections
            .map((section) => ({
                ...section,
                groups: all
                    .filter((g) => g.configType === section.type)
                    .sort((a, b) => a.providerName.localeCompare(b.providerName)),
            }))
            .filter((section) => section.groups.length > 0);
    });

    public capabilities = computed<SelectItem[]>(() => [
        { name: 'All Capabilities', value: null },
        ...this.configs().flatMap((config) => config.tags.map((tag) => ({ name: tag.name, value: tag.name }))),
    ]);

    ngOnInit() {
        this.llmLibraryService
            .loadConfigs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.configsLoaded.set(true));

        for (const p of this.voiceProviders) {
            p.storage.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        }
    }

    onAddConfig(provider: VoiceProvider): void {
        this.dialog.open(RealtimeConfigDialogComponent, {
            disableClose: true,
            data: { config: null, action: 'create', provider: provider.key },
        });
    }

    onEditConfig(provider: VoiceProvider, config: VoiceProviderConfig): void {
        this.dialog.open(RealtimeConfigDialogComponent, {
            disableClose: true,
            data: { config, action: 'update', provider: provider.key },
        });
    }

    onDeleteConfig(provider: VoiceProvider, config: VoiceProviderConfig): void {
        this.confirmationDialogService
            .confirmDelete(config.custom_name)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result !== true) return;
                provider.storage.deleteConfig(config.id).subscribe({
                    next: () => this.toast.success(`${provider.label} config deleted.`),
                    error: () => this.toast.error('Failed to delete config.'),
                });
            });
    }

    public onSearchChange(value: string): void {
        this.searchQuery.set(value);
    }

    public onAddModel(): void {
        this.dialog.open(AddConfigurationDialogComponent);
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

    public onDelete(model: LlmLibraryModel): void {
        const opts: ConfirmationDialogData = {
            title: 'Delete the model?',
            message: `Are you sure you want to delete the ${model.customName} model? This will delete it in all agents, tools and flows.`,
            type: 'danger',
        };

        this.confirmationDialogService
            .confirm(opts)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result !== true) return;

                const delete$: Partial<Record<ModelTypes, () => Observable<void>>> = {
                    [ModelTypes.LLM]: () => this.llmConfigStorageService.deleteConfig(model.id),
                    [ModelTypes.EMBEDDING]: () => this.embeddingConfigStorage.deleteConfig(model.id),
                };

                delete$[model.configType]?.().subscribe({
                    next: () => {
                        this.toast.success('Configuration deleted.');
                        this.defaultModelsStorageService.markDefaultModelsOutdated();
                    },
                });
            });
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
