import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, Inject, OnDestroy, OnInit } from '@angular/core';
import { FormControl, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { forkJoin, of, Subject, takeUntil } from 'rxjs';

import { GetCollectionRequest } from '../../../../features/knowledge-sources/models/collection.model';
import { CollectionsApiService } from '../../../../features/knowledge-sources/services/collections-api.service';
import {
    FullLLMConfig,
    FullLLMConfigService,
} from '../../../../features/settings-dialog/services/llms/full-llm-config.service';
import { LLM_Config_Service } from '../../../../features/settings-dialog/services/llms/llm-config.service';
import { LLM_Models_Service } from '../../../../features/settings-dialog/services/llms/llm-models.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { IconButtonComponent } from '../../../../shared/components/buttons/icon-button/icon-button.component';
import { KnowledgeSelectorComponent } from '../../../../shared/components/knowledge-selector/knowledge-selector.component';
import { LlmModelSelectorComponent } from '../../../../shared/components/llm-model-selector/llm-model-selector.component';
import { SelectComponent, SelectItem } from '../../../../shared/components/select/select.component';
import { MATERIAL_FORMS } from '../../../../shared/material-forms';

export interface AdvancedSettingsData {
    id: number;
    fullFcmLlmConfig?: FullLLMConfig;
    agentRole: string;
    max_iter: number;
    max_rpm: number | null;
    max_execution_time: number | null;
    max_retry_limit: number | null;
    default_temperature: number | null;
    knowledge_collection?: number | null;
    rag: {
        rag_id: number;
        rag_type: string;
        rag_status?: string;
    } | null;
    search_configs: {
        naive: {
            similarity_threshold: number | null;
            search_limit: number | null;
        };
    };
    selected_knowledge_source?: GetCollectionRequest | null; // For display purposes only
    memory: boolean;
    cache: boolean;
    respect_context_window: boolean;
}

@Component({
    selector: 'app-advanced-settings-dialog',
    imports: [
        FormsModule,
        ReactiveFormsModule,
        ...MATERIAL_FORMS,
        AppSvgIconComponent,
        KnowledgeSelectorComponent,
        IconButtonComponent,
        LlmModelSelectorComponent,
        SelectComponent,
    ],
    templateUrl: './advanced-settings-dialog.component.html',
    styleUrls: ['./advanced-settings-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdvancedSettingsDialogComponent implements OnInit, OnDestroy {
    public agentData: AdvancedSettingsData;
    public combinedLLMs: FullLLMConfig[] = [];
    public selectedLlmId: number | null = null;
    public isLoadingLLMs = false;

    // Knowledge sources
    public allKnowledgeSources: GetCollectionRequest[] = [];
    public agentRagsSelectItems: SelectItem[] = [];
    public isLoadingKnowledgeSources = false;
    public knowledgeSourcesError: string | null = null;

    private readonly _destroyed$ = new Subject<void>();
    public search_limit = 3;

    // Form controls for sliders
    public maxIterControl = new FormControl(10, [Validators.min(1), Validators.max(30)]);
    public maxRpmControl = new FormControl(10, [Validators.min(1), Validators.max(30)]);
    public maxExecutionTimeControl = new FormControl(60, [Validators.min(1), Validators.max(300)]);
    public maxRetryLimitControl = new FormControl(3, [Validators.min(0), Validators.max(10)]);
    public searchLimitControl = new FormControl(3, [Validators.min(1), Validators.max(1000)]);
    public similarityThresholdControl = new FormControl<number | null>(0.2, [Validators.min(0.0), Validators.max(1.0)]);
    public memoryControl = new FormControl(false);
    public cacheControl = new FormControl(true);
    public respectContextWindowControl = new FormControl(true);

    constructor(
        public dialogRef: DialogRef<AdvancedSettingsData>,
        @Inject(DIALOG_DATA) public data: AdvancedSettingsData,
        private llmConfigService: LLM_Config_Service,
        private llmModelsService: LLM_Models_Service,
        private fullLLMConfigService: FullLLMConfigService,
        private collectionsService: CollectionsApiService,
        private cdr: ChangeDetectorRef
    ) {
        // Initialize your local data from the injected data
        this.agentData = { ...data };

        // Initialize form controls with data
        this.maxIterControl.setValue(data.max_iter ?? 10);
        this.maxRpmControl.setValue(data.max_rpm ?? 10);
        this.maxExecutionTimeControl.setValue(data.max_execution_time ?? 60);
        this.maxRetryLimitControl.setValue(data.max_retry_limit ?? 3);
        const st = data.search_configs?.naive?.similarity_threshold;
        const threshold = st ?? 0.2;
        this.similarityThresholdControl.setValue(threshold);
        const sl = data.search_configs?.naive?.search_limit;
        this.searchLimitControl.setValue(sl ?? 3);
        this.search_limit =
            this.agentData.search_configs.naive.search_limit !== null
                ? this.agentData.search_configs.naive.search_limit
                : 3;

        // Set default_temperature to null as requested
        this.agentData.default_temperature = null;

        // Initialize boolean controls with data or defaults
        this.memoryControl.setValue(data.memory ?? false);
        this.cacheControl.setValue(data.cache ?? true);
        this.respectContextWindowControl.setValue(data.respect_context_window ?? true);

        // Initialize selected LLM ID from fullFcmLlmConfig if present
        if (this.agentData.fullFcmLlmConfig) {
            this.selectedLlmId = this.agentData.fullFcmLlmConfig.id;
        } else {
            this.selectedLlmId = null; // "Same as LLM" option
        }
    }

    // In ngOnInit
    public ngOnInit(): void {
        // Fetch LLM configs, models, and knowledge sources
        const collectionId = this.agentData.knowledge_collection;
        this.isLoadingKnowledgeSources = true;
        this.isLoadingLLMs = true;

        forkJoin({
            llmConfigs: this.fullLLMConfigService.getFullLLMConfigs(),
            knowledgeSources: this.collectionsService.getCollections(),
            rags: collectionId ? this.collectionsService.getRagsByCollectionId(collectionId) : of([]),
        })
            .pipe(takeUntil(this._destroyed$))
            .subscribe({
                next: ({ llmConfigs, knowledgeSources, rags }) => {
                    this.agentRagsSelectItems = rags.map((rag) => ({ name: rag.rag_type, value: rag.rag_id }));

                    // Process LLM configs
                    this.combinedLLMs = llmConfigs;

                    // Make sure the selected LLM ID is set correctly
                    if (this.agentData.fullFcmLlmConfig) {
                        // Find the matching LLM config in our loaded configs
                        const matchingConfig = llmConfigs.find(
                            (config) => config.id === this.agentData.fullFcmLlmConfig?.id
                        );

                        if (matchingConfig) {
                            this.selectedLlmId = matchingConfig.id;
                            // Force UI update with setTimeout
                            setTimeout(() => {
                                this.selectedLlmId = matchingConfig.id;
                                this.cdr.markForCheck();
                            });
                        } else {
                            console.log('No matching LLM config found');
                        }
                    }

                    // Process knowledge sources
                    this.allKnowledgeSources = knowledgeSources;

                    // Set selected knowledge source based on the ID
                    if (this.agentData.knowledge_collection) {
                        const foundSource = this.allKnowledgeSources.find(
                            (source) => source.collection_id === this.agentData.knowledge_collection
                        );

                        this.agentData.selected_knowledge_source = foundSource || null;

                        // console.log(
                        //     'Selected knowledge source after initialization:',
                        //     this.agentData.selected_knowledge_source
                        //         ? `${this.agentData.selected_knowledge_source.collection_name} (ID: ${this.agentData.selected_knowledge_source.collection_id})`
                        //         : 'None'
                        // );
                    } else {
                        console.log('No knowledge_collection ID provided in initial data');
                    }

                    this.isLoadingKnowledgeSources = false;
                    this.isLoadingLLMs = false;
                    this.cdr.markForCheck();
                },
                error: (err) => {
                    console.error('Error fetching data:', err);
                    this.knowledgeSourcesError = 'Failed to load knowledge sources';
                    this.isLoadingKnowledgeSources = false;
                    this.isLoadingLLMs = false;
                    this.cdr.markForCheck();
                },
            });

        this.dialogRef.backdropClick.pipe(takeUntil(this._destroyed$)).subscribe(() => this.closeAndApply());

        this.dialogRef.keydownEvents.pipe(takeUntil(this._destroyed$)).subscribe((e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                this.closeAndApply();
            }
        });
    }

    public onLlmChange(llmId: number | null): void {
        this.selectedLlmId = llmId;

        if (llmId === null) {
            // "Default to LLM" option selected
            this.agentData.fullFcmLlmConfig = undefined;
        } else {
            // Find the selected LLM config
            const selectedLlm = this.combinedLLMs.find((llm) => llm.id === llmId);
            if (selectedLlm) {
                this.agentData.fullFcmLlmConfig = selectedLlm;
            }
        }
        this.cdr.markForCheck();
    }

    public onAgentRagChange(value: unknown): void {
        const ragId = typeof value === 'number' ? value : Number(value);
        if (!Number.isFinite(ragId)) {
            this.agentData.rag = null;
            return;
        }
        this.agentData.rag = {
            rag_id: ragId,
            rag_type: 'naive',
        };
    }

    public onKnowledgeSourceChange(collectionId: number | null): void {
        this.agentData.knowledge_collection = collectionId;

        if (collectionId === null) {
            this.agentData.selected_knowledge_source = null;
            this.agentRagsSelectItems = [];
        } else {
            const selectedCollection = this.allKnowledgeSources.find((source) => source.collection_id === collectionId);
            this.agentData.selected_knowledge_source = selectedCollection || null;

            this.getRagsByCollectionId(collectionId);
        }
        this.agentData.rag = null;
        this.cdr.markForCheck();
    }

    private getRagsByCollectionId(id: number): void {
        this.collectionsService
            .getRagsByCollectionId(id)
            .pipe(takeUntil(this._destroyed$))
            .subscribe((rags) => {
                this.agentRagsSelectItems = rags.map((rag) => ({
                    name: rag.rag_type,
                    value: rag.rag_id,
                }));
            });
    }

    public onThresholdChange(event: { value: number | null }): void {
        const value = event?.value;
        const normalizedValue = value === null || value === undefined ? 0.2 : Number(value);
        this.similarityThresholdControl.setValue(normalizedValue);
    }

    public onSearchLimitChange(value: number | null): void {
        this.agentData.search_configs.naive.search_limit = value ?? null;
    }

    // Formatting methods for sliders
    formatIterationLabel(value: number): string {
        return `${value}`;
    }

    formatExecutionTimeLabel(value: number): string {
        return `${value}s`;
    }

    formatRetryLimitLabel(value: number): string {
        return `${value}`;
    }

    formatRpmLabel(value: number): string {
        return `${value}`;
    }

    formatSearchLimitLabel(value: number): string {
        return `${value}`;
    }

    formatThresholdLabel(value: number): string {
        return `${value}`;
    }

    // In save method
    public save(): void {
        // Update agentData with current form control values
        this.agentData.max_iter = this.maxIterControl.value || 10;
        this.agentData.max_rpm = this.maxRpmControl.value || 10;
        this.agentData.max_execution_time = this.maxExecutionTimeControl.value || 60;
        this.agentData.max_retry_limit = this.maxRetryLimitControl.value ?? 3;
        this.agentData.search_configs = {
            naive: {
                search_limit: this.searchLimitControl.value || 3,
                similarity_threshold: this.similarityThresholdControl.value ?? 0.2,
            },
        };

        this.agentData.memory = this.memoryControl.value ?? false;
        this.agentData.cache = this.cacheControl.value ?? true;
        this.agentData.respect_context_window = this.respectContextWindowControl.value ?? true;

        // Create a deep copy to prevent any unintended references
        const result = JSON.parse(JSON.stringify(this.agentData));

        this.dialogRef.close(result);
    }

    public ngOnDestroy(): void {
        this._destroyed$.next();
        this._destroyed$.complete();
    }

    public closeAndApply(): void {
        this.save();
    }
}
