import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    DestroyRef,
    Inject,
    inject,
    OnInit,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { AppSvgIconComponent, IconButtonComponent, TabButtonComponent } from '@shared/components';
import { FullLLMConfig, FullLLMConfigService } from '@shared/services';
import { forkJoin, of } from 'rxjs';

import {
    GetCollectionRagsResponse,
    GetCollectionRequest,
} from '../../../../features/knowledge-sources/models/collection.model';
import { CollectionsApiService } from '../../../../features/knowledge-sources/services/collections-api.service';
import { AgentRag } from '../../../../features/staff/models/agent.model';
import {
    AdvancedTabComponent,
    ExecutionTabComponent,
    GeneralTabComponent,
    RagTabComponent,
    Tab,
    TabId,
} from '../../../../shared/components/create-agent-form-dialog/tabs';
import { AgentSearchConfigs } from '../../../../shared/models';

export interface AdvancedSettingsData {
    id: number;
    role: string;
    max_iter: number;
    max_rpm: number | null;
    max_execution_time: number | null;
    max_retry_limit: number | null;
    default_temperature: number | null;
    knowledge_collection?: number | null;
    fcm_llm_config: number | null;
    rag: AgentRag | null;
    search_configs: AgentSearchConfigs;
    memory: boolean;
    cache: boolean;
    respect_context_window: boolean;
    _saveAfterClose?: boolean;
}

@Component({
    selector: 'app-advanced-settings-dialog',
    imports: [
        FormsModule,
        ReactiveFormsModule,
        IconButtonComponent,
        AdvancedTabComponent,
        ExecutionTabComponent,
        RagTabComponent,
        GeneralTabComponent,
        TabButtonComponent,
        AppSvgIconComponent,
    ],
    templateUrl: './advanced-settings-dialog.component.html',
    styleUrls: ['./advanced-settings-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdvancedSettingsDialogComponent implements OnInit {
    private fb = inject(FormBuilder);
    private destroyRef = inject(DestroyRef);

    activeTab = signal<TabId>(TabId.GENERAL);
    loadingLLMs = signal(true);
    loadingKnowledgeSources = signal(true);
    loadingRags = signal(false);

    public combinedLLMs: FullLLMConfig[] = [];
    public form!: FormGroup;
    public allKnowledgeSources: GetCollectionRequest[] = [];
    private _closeWithPageSave = false;
    public agentRags: GetCollectionRagsResponse[] = [];
    public tabs: Tab[] = [
        { id: TabId.GENERAL, label: 'General' },
        { id: TabId.RAG, label: 'RAG' },
        // { id: TabId.LLM_PARAMS, label: 'LLM Params' },
        { id: TabId.EXECUTION, label: 'Execution' },
        { id: TabId.ADVANCED, label: 'Advanced' },
    ];

    constructor(
        public dialogRef: DialogRef<AdvancedSettingsData>,
        @Inject(DIALOG_DATA) public data: AdvancedSettingsData,
        private fullLLMConfigService: FullLLMConfigService,
        private collectionsService: CollectionsApiService,
        private cdr: ChangeDetectorRef
    ) {}

    // In ngOnInit
    public ngOnInit(): void {
        this.initForm();

        // Fetch LLM configs, models, and knowledge sources
        const collectionId = this.data.knowledge_collection;
        if (collectionId) this.loadingRags.set(true);
        forkJoin({
            llmConfigs: this.fullLLMConfigService.getFullLLMConfigs(),
            knowledgeSources: this.collectionsService.getCollections(),
            rags: collectionId ? this.collectionsService.getRagsByCollectionId(collectionId) : of([]),
        })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: ({ llmConfigs, knowledgeSources, rags }) => {
                    this.agentRags = rags;
                    this.combinedLLMs = llmConfigs;
                    this.allKnowledgeSources = knowledgeSources;
                    this.loadingLLMs.set(false);
                    this.loadingKnowledgeSources.set(false);
                    this.loadingRags.set(false);
                    this.cdr.markForCheck();
                },
                error: (err) => {
                    console.error('Error fetching data:', err);
                    this.loadingLLMs.set(false);
                    this.loadingKnowledgeSources.set(false);
                    this.loadingRags.set(false);
                    this.cdr.markForCheck();
                },
            });

        this.form
            .get('knowledge_collection')
            ?.valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((id) => this.onKnowledgeSourceChange(id));

        this.dialogRef.backdropClick.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.save());

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                this.save();
            }
            if ((e.ctrlKey || e.metaKey) && e.code === 'KeyS') {
                e.preventDefault();
                e.stopPropagation();
                this._closeWithPageSave = true;
                this.save();
            }
        });
    }

    private initForm(): void {
        const data = this.data;
        const ragValidators = data.knowledge_collection ? [Validators.required] : [];
        this.form = this.fb.group({
            role: [data.role],
            max_iter: [data.max_iter || 10, [Validators.min(1), Validators.max(30)]],
            max_rpm: [data.max_rpm || 10, [Validators.min(1), Validators.max(30)]],
            max_execution_time: [data.max_execution_time || 60, [Validators.min(1), Validators.max(600)]],
            max_retry_limit: [data.max_retry_limit || 3, [Validators.min(0), Validators.max(10)]],
            cache: [data.cache ?? false],
            respect_context_window: [data.respect_context_window ?? false],
            fcm_llm_config: [data.fcm_llm_config || null],
            knowledge_collection: [data.knowledge_collection || null],
            rag: [data.rag?.rag_id ? { rag_id: data.rag.rag_id, rag_type: data.rag.rag_type } : null, ragValidators],
            search_configs: [data.search_configs || null],
        });
    }

    private onKnowledgeSourceChange(collectionId: number | null): void {
        const ragControl = this.form.get('rag');
        if (collectionId === null) {
            this.agentRags = [];
            ragControl?.clearValidators();
        } else {
            this.getRagsByCollectionId(collectionId);
            ragControl?.markAsTouched();
            ragControl?.setValidators([Validators.required]);
        }
        ragControl?.patchValue(null);
        ragControl?.updateValueAndValidity();
    }

    private getRagsByCollectionId(id: number): void {
        this.loadingRags.set(true);
        this.collectionsService
            .getRagsByCollectionId(id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (rags) => {
                    this.agentRags = rags;
                    this.loadingRags.set(false);
                    this.cdr.markForCheck();
                },
                error: () => this.loadingRags.set(false),
            });
    }

    // In save method
    public save(): void {
        if (this.form.invalid) return;

        const { search_configs, rag, ...rest } = this.form.value;
        const result = {
            ...rest,
            rag,
            search_configs: rag?.rag_type ? { ...this.data.search_configs, [rag.rag_type]: search_configs } : null,
        };

        // Update agentData with current form control values
        const closeWithSave = this._closeWithPageSave;
        this._closeWithPageSave = false;
        this.dialogRef.close({ ...result, _saveAfterClose: closeWithSave } as AdvancedSettingsData);
    }

    protected readonly TabId = TabId;
}
