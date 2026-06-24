import { NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    input,
    OnInit,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    AppSvgIconComponent,
    ButtonComponent,
    DualSliderComponent,
    HelpTooltipComponent,
    InputNumberComponent,
    RadioButtonComponent,
    SelectComponent,
    SelectItem,
    SliderWithStepperComponent,
    TextareaComponent,
    ToggleSwitchComponent,
    ValidationErrorsComponent,
} from '@shared/components';

import {
    GetCollectionRagsResponse,
    GetCollectionRequest,
} from '../../../../../features/knowledge-sources/models/collection.model';
import { AgentRag } from '../../../../../features/staff/models/agent.model';
import { AgentsService } from '../../../../../features/staff/services/staff.service';
import {
    AgentSearchConfigs,
    GraphBasicSearchConfig,
    GraphDriftSearchConfig,
    GraphGlobalSearchConfig,
    GraphLocalSearchConfig,
    GraphSearchMethod,
    SuggestResponse,
} from '../../../../models';

type SuggestKey = GraphSearchMethod | 'naive';

export const GRAPH_BASIC_DEFAULTS: GraphBasicSearchConfig = {
    prompt: null,
    k: 10,
    max_context_tokens: 12000,
};

export const GRAPH_LOCAL_DEFAULTS: GraphLocalSearchConfig = {
    prompt: null,
    text_unit_prop: 0.5,
    community_prop: 0.15,
    conversation_history_max_turns: 5,
    max_context_tokens: 12000,
    top_k_entities: 10,
    top_k_relationships: 10,
    community_level: 2,
};

export const GRAPH_GLOBAL_DEFAULTS: GraphGlobalSearchConfig = {
    map_prompt: null,
    reduce_prompt: null,
    knowledge_prompt: null,
    max_context_tokens: 12000,
    data_max_tokens: 12000,
    map_max_length: 1000,
    reduce_max_length: 2000,
    dynamic_community_selection: false,
    dynamic_search_threshold: 1,
    dynamic_search_keep_parent: false,
    dynamic_search_num_repeats: 1,
    dynamic_search_use_summary: false,
    dynamic_search_max_level: 2,
};

export const GRAPH_DRIFT_DEFAULTS: GraphDriftSearchConfig = {
    prompt: null,
    reduce_prompt: null,
    data_max_tokens: 12000,
    reduce_max_tokens: null,
    reduce_max_completion_tokens: null,
    concurrency: 32,
    drift_k_followups: 20,
    primer_folds: 5,
    primer_llm_max_tokens: 12000,
    n_depth: 3,
    local_search_text_unit_prop: 0.9,
    local_search_community_prop: 0.1,
    local_search_top_k_mapped_entities: 10,
    local_search_top_k_relationships: 10,
    local_search_max_data_tokens: 12000,
    local_search_top_p: 1.0,
    local_search_n: 1,
    local_search_llm_max_gen_tokens: null,
    local_search_llm_max_gen_completion_tokens: null,
    community_level: 2,
};

@Component({
    selector: 'app-rag-tab',
    templateUrl: './rag-tab.component.html',
    styleUrls: ['../tab.component.scss'],
    imports: [
        ReactiveFormsModule,
        NgTemplateOutlet,
        SelectComponent,
        SliderWithStepperComponent,
        RadioButtonComponent,
        InputNumberComponent,
        DualSliderComponent,
        TextareaComponent,
        ValidationErrorsComponent,
        ToggleSwitchComponent,
        AppSvgIconComponent,
        ButtonComponent,
        HelpTooltipComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RagTabComponent implements OnInit {
    private fb = inject(FormBuilder);
    private destroyRef = inject(DestroyRef);
    private agentsService = inject(AgentsService);

    form = input.required<FormGroup>();
    allKnowledgeSources = input.required<GetCollectionRequest[]>();
    agentRags = input.required<GetCollectionRagsResponse[]>();
    searchConfigs = input.required<AgentSearchConfigs | null>();
    loadingKnowledgeSources = input<boolean>(false);
    loadingRags = input<boolean>(false);
    llmConfigId = input<number | null>(null);

    selectedRagType = signal<'naive' | 'graph' | null>(null);
    activeGraphMethodSignal = signal<GraphSearchMethod | null>(null);
    recommendedSearchMethod = signal<GraphSearchMethod | null>(null);
    suggestingFor = signal<SuggestKey | null>(null);
    suggestErrorFor = signal<SuggestKey | null>(null);

    featureAvailable = computed<boolean>(() => this.llmConfigId() != null);

    tokenLimitsLoading = signal<boolean>(false);
    tokenLimitsError = signal<string | null>(null);
    effectiveLlmContextWindow = signal<number | null>(null);
    safeTokenBudget = signal<number | null>(null);

    searchParamsReady = computed<boolean>(
        () =>
            this.featureAvailable() &&
            !this.tokenLimitsLoading() &&
            this.tokenLimitsError() == null &&
            this.effectiveLlmContextWindow() != null
    );

    tokenWarningMsg = computed<string>(() => {
        const safe = this.safeTokenBudget();
        return safe != null ? `Above recommended budget (${safe.toLocaleString()} tokens).` : '';
    });

    tokenErrorMsg = computed<string>(() => {
        const ctx = this.effectiveLlmContextWindow();
        return ctx != null ? `Exceeds this LLM's context window (${ctx.toLocaleString()} tokens).` : '';
    });

    // Cache token limits per llm_config_id for the dialog's lifetime.
    private tokenLimitsCache = new Map<number, { ctx: number; safe: number }>();
    private fetchToken = 0;
    private lastLlmConfigId: number | null = null;

    // Guard so the initial recommendation fetch fires once per
    // (collection, llm, ragType) triple, not on every signal touch.
    private lastRecommendationKey: string | null = null;

    knowledgeSelectItems = computed<SelectItem[]>(() => {
        return [
            {
                name: 'No collection',
                value: null,
            },
            ...this.allKnowledgeSources().map((item) => ({
                name: item.collection_name,
                value: item.collection_id,
            })),
        ];
    });
    agentRagSelectItems = computed<SelectItem<AgentRag>[]>(() => {
        return this.agentRags().map((item) => ({
            name: item.rag_type,
            value: {
                rag_id: item.rag_id,
                rag_type: item.rag_type,
            },
        }));
    });

    searchConfigsFormGroup: FormGroup | null = null;
    searchTypes = computed<(SelectItem<GraphSearchMethod> & { icon?: string; tooltip?: string })[]>(() => {
        const rec = this.recommendedSearchMethod();
        const recTooltip = 'Recommended for your current configuration.';
        return [
            {
                name: 'Basic',
                value: 'basic',
                icon: rec === 'basic' ? 'star' : undefined,
                tooltip: rec === 'basic' ? recTooltip : undefined,
            },
            {
                name: 'Local',
                value: 'local',
                icon: rec === 'local' ? 'star' : undefined,
                tooltip: rec === 'local' ? recTooltip : undefined,
            },
            {
                name: 'Global',
                value: 'global_search',
                icon: rec === 'global_search' ? 'star' : undefined,
                tooltip: rec === 'global_search' ? recTooltip : undefined,
            },
            {
                name: 'DRIFT',
                value: 'drift_search',
                icon: rec === 'drift_search' ? 'star' : undefined,
                tooltip: rec === 'drift_search' ? recTooltip : undefined,
            },
        ];
    });

    activeKey = computed<SuggestKey>(() => {
        if (this.selectedRagType() === 'naive') return 'naive';
        return (this.activeGraphMethodSignal() ?? 'basic') as SuggestKey;
    });

    textUnitProportionControl!: FormControl;
    communityProportionControl!: FormControl;
    driftLocalTextUnitPropControl!: FormControl;
    driftLocalCommunityPropControl!: FormControl;

    constructor() {
        effect(() => {
            const id = this.llmConfigId();
            if (id !== this.lastLlmConfigId) {
                this.lastLlmConfigId = id;
                this.maybeFetchSearchMetadata();
            }
        });
    }

    ngOnInit() {
        const ragControl = this.form().get('rag');
        const ragControlValue = ragControl?.value;

        if (ragControlValue) {
            this.selectedRagType.set(ragControlValue.rag_type);
            this.initSearchConfigsFormGroup(ragControlValue.rag_type);
        }

        ragControl?.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((rag) => {
            this.resetSuggestState();
            if (!rag) {
                this.searchConfigsFormGroup = null;
                this.selectedRagType.set(null);
                return;
            }
            this.selectedRagType.set(rag.rag_type);
            this.initSearchConfigsFormGroup(rag.rag_type);
            this.maybeFetchSearchMetadata();
        });

        this.form()
            .get('knowledge_collection')
            ?.valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => {
                this.resetSuggestState();
                this.maybeFetchSearchMetadata();
            });

        // First mount: fire if everything's already there.
        this.maybeFetchSearchMetadata();
    }

    private initSearchConfigsFormGroup(ragType: string): void {
        const configs = this.searchConfigs();
        if (ragType === 'naive') {
            this.searchConfigsFormGroup = this.fb.group({
                search_limit: [configs?.naive?.search_limit ?? 3, [Validators.min(1), Validators.max(1000)]],
                similarity_threshold: [
                    configs?.naive?.similarity_threshold ?? 0.2,
                    [Validators.min(0.0), Validators.max(1.0)],
                ],
            });
        }

        if (ragType === 'graph') {
            const initialMethod = (configs?.graph?.search_method ?? 'basic') as GraphSearchMethod;
            this.searchConfigsFormGroup = this.fb.group({
                search_method: [initialMethod, [Validators.required]],
                basic: this.initGraphBasicSearchConfig(configs?.graph?.basic),
                local: this.initGraphLocalSearchConfig(configs?.graph?.local),
                global_search: this.initGraphGlobalSearchConfig(configs?.graph?.global_search),
                drift_search: this.initGraphDriftSearchConfig(configs?.graph?.drift_search),
            });
            this.activeGraphMethodSignal.set(initialMethod);
            this.searchConfigsFormGroup
                .get('search_method')
                ?.valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((m) => this.activeGraphMethodSignal.set((m as GraphSearchMethod) ?? null));

            this.wireDynamicCommunityToggle();
        } else {
            this.activeGraphMethodSignal.set(null);
        }

        this.form().setControl('search_configs', this.searchConfigsFormGroup);
    }

    private initGraphBasicSearchConfig(configs: GraphBasicSearchConfig | undefined): FormGroup {
        return this.fb.group({
            prompt: [configs?.prompt ?? GRAPH_BASIC_DEFAULTS.prompt, [Validators.maxLength(1000)]],
            k: [configs?.k ?? GRAPH_BASIC_DEFAULTS.k, [Validators.required, Validators.min(1), Validators.max(100)]],
            max_context_tokens: [
                configs?.max_context_tokens ?? GRAPH_BASIC_DEFAULTS.max_context_tokens,
                [Validators.required, Validators.min(100), Validators.max(100000)],
            ],
        });
    }

    private initGraphLocalSearchConfig(configs: GraphLocalSearchConfig | undefined): FormGroup {
        this.textUnitProportionControl = this.fb.control(
            configs?.text_unit_prop ?? GRAPH_LOCAL_DEFAULTS.text_unit_prop,
            [Validators.required, Validators.min(0), Validators.max(1)]
        );

        this.communityProportionControl = this.fb.control(
            configs?.community_prop ?? GRAPH_LOCAL_DEFAULTS.community_prop,
            [Validators.required, Validators.min(0), Validators.max(1)]
        );

        return this.fb.group({
            prompt: [configs?.prompt ?? GRAPH_LOCAL_DEFAULTS.prompt, [Validators.maxLength(1000)]],
            text_unit_prop: this.textUnitProportionControl,
            community_prop: this.communityProportionControl,
            conversation_history_max_turns: [
                configs?.conversation_history_max_turns ?? GRAPH_LOCAL_DEFAULTS.conversation_history_max_turns,
                [Validators.required, Validators.min(1), Validators.max(50)],
            ],
            max_context_tokens: [
                configs?.max_context_tokens ?? GRAPH_LOCAL_DEFAULTS.max_context_tokens,
                [Validators.required, Validators.min(100), Validators.max(100000)],
            ],
            top_k_entities: [
                configs?.top_k_entities ?? GRAPH_LOCAL_DEFAULTS.top_k_entities,
                [Validators.required, Validators.min(1), Validators.max(100)],
            ],
            top_k_relationships: [
                configs?.top_k_relationships ?? GRAPH_LOCAL_DEFAULTS.top_k_relationships,
                [Validators.required, Validators.min(1), Validators.max(100)],
            ],
            community_level: [configs?.community_level ?? GRAPH_LOCAL_DEFAULTS.community_level],
        });
    }

    private initGraphGlobalSearchConfig(configs: GraphGlobalSearchConfig | undefined): FormGroup {
        return this.fb.group({
            map_prompt: [configs?.map_prompt ?? GRAPH_GLOBAL_DEFAULTS.map_prompt],
            reduce_prompt: [configs?.reduce_prompt ?? GRAPH_GLOBAL_DEFAULTS.reduce_prompt],
            knowledge_prompt: [configs?.knowledge_prompt ?? GRAPH_GLOBAL_DEFAULTS.knowledge_prompt],
            max_context_tokens: [
                configs?.max_context_tokens ?? GRAPH_GLOBAL_DEFAULTS.max_context_tokens,
                [Validators.required, Validators.min(100), Validators.max(100000)],
            ],
            data_max_tokens: [
                configs?.data_max_tokens ?? GRAPH_GLOBAL_DEFAULTS.data_max_tokens,
                [Validators.required, Validators.min(100), Validators.max(100000)],
            ],
            map_max_length: [
                configs?.map_max_length ?? GRAPH_GLOBAL_DEFAULTS.map_max_length,
                [Validators.required, Validators.min(1), Validators.max(10000)],
            ],
            reduce_max_length: [
                configs?.reduce_max_length ?? GRAPH_GLOBAL_DEFAULTS.reduce_max_length,
                [Validators.required, Validators.min(1), Validators.max(10000)],
            ],
            dynamic_community_selection: [
                configs?.dynamic_community_selection ?? GRAPH_GLOBAL_DEFAULTS.dynamic_community_selection,
            ],
            dynamic_search_threshold: [
                configs?.dynamic_search_threshold ?? GRAPH_GLOBAL_DEFAULTS.dynamic_search_threshold,
                [Validators.required, Validators.min(1), Validators.max(10)],
            ],
            dynamic_search_keep_parent: [
                configs?.dynamic_search_keep_parent ?? GRAPH_GLOBAL_DEFAULTS.dynamic_search_keep_parent,
            ],
            dynamic_search_num_repeats: [
                configs?.dynamic_search_num_repeats ?? GRAPH_GLOBAL_DEFAULTS.dynamic_search_num_repeats,
                [Validators.required, Validators.min(1), Validators.max(5)],
            ],
            dynamic_search_use_summary: [
                configs?.dynamic_search_use_summary ?? GRAPH_GLOBAL_DEFAULTS.dynamic_search_use_summary,
            ],
            dynamic_search_max_level: [
                configs?.dynamic_search_max_level ?? GRAPH_GLOBAL_DEFAULTS.dynamic_search_max_level,
                [Validators.required, Validators.min(1), Validators.max(5)],
            ],
        });
    }

    private initGraphDriftSearchConfig(configs: GraphDriftSearchConfig | undefined): FormGroup {
        this.driftLocalTextUnitPropControl = this.fb.control(
            configs?.local_search_text_unit_prop ?? GRAPH_DRIFT_DEFAULTS.local_search_text_unit_prop,
            [Validators.required, Validators.min(0), Validators.max(1)]
        );
        this.driftLocalCommunityPropControl = this.fb.control(
            configs?.local_search_community_prop ?? GRAPH_DRIFT_DEFAULTS.local_search_community_prop,
            [Validators.required, Validators.min(0), Validators.max(1)]
        );

        return this.fb.group({
            prompt: [configs?.prompt ?? GRAPH_DRIFT_DEFAULTS.prompt],
            reduce_prompt: [configs?.reduce_prompt ?? GRAPH_DRIFT_DEFAULTS.reduce_prompt],
            data_max_tokens: [
                configs?.data_max_tokens ?? GRAPH_DRIFT_DEFAULTS.data_max_tokens,
                [Validators.required, Validators.min(100), Validators.max(100000)],
            ],
            reduce_max_tokens: [configs?.reduce_max_tokens ?? GRAPH_DRIFT_DEFAULTS.reduce_max_tokens],
            reduce_max_completion_tokens: [
                configs?.reduce_max_completion_tokens ?? GRAPH_DRIFT_DEFAULTS.reduce_max_completion_tokens,
            ],
            concurrency: [
                configs?.concurrency ?? GRAPH_DRIFT_DEFAULTS.concurrency,
                [Validators.required, Validators.min(1), Validators.max(256)],
            ],
            drift_k_followups: [
                configs?.drift_k_followups ?? GRAPH_DRIFT_DEFAULTS.drift_k_followups,
                [Validators.required, Validators.min(1), Validators.max(100)],
            ],
            primer_folds: [
                configs?.primer_folds ?? GRAPH_DRIFT_DEFAULTS.primer_folds,
                [Validators.required, Validators.min(1), Validators.max(50)],
            ],
            primer_llm_max_tokens: [
                configs?.primer_llm_max_tokens ?? GRAPH_DRIFT_DEFAULTS.primer_llm_max_tokens,
                [Validators.required, Validators.min(100), Validators.max(100000)],
            ],
            n_depth: [
                configs?.n_depth ?? GRAPH_DRIFT_DEFAULTS.n_depth,
                [Validators.required, Validators.min(1), Validators.max(10)],
            ],
            local_search_text_unit_prop: this.driftLocalTextUnitPropControl,
            local_search_community_prop: this.driftLocalCommunityPropControl,
            local_search_top_k_mapped_entities: [
                configs?.local_search_top_k_mapped_entities ?? GRAPH_DRIFT_DEFAULTS.local_search_top_k_mapped_entities,
                [Validators.required, Validators.min(1), Validators.max(100)],
            ],
            local_search_top_k_relationships: [
                configs?.local_search_top_k_relationships ?? GRAPH_DRIFT_DEFAULTS.local_search_top_k_relationships,
                [Validators.required, Validators.min(1), Validators.max(100)],
            ],
            local_search_max_data_tokens: [
                configs?.local_search_max_data_tokens ?? GRAPH_DRIFT_DEFAULTS.local_search_max_data_tokens,
                [Validators.required, Validators.min(100), Validators.max(100000)],
            ],
            local_search_top_p: [
                configs?.local_search_top_p ?? GRAPH_DRIFT_DEFAULTS.local_search_top_p,
                [Validators.required, Validators.min(0), Validators.max(1)],
            ],
            local_search_n: [
                configs?.local_search_n ?? GRAPH_DRIFT_DEFAULTS.local_search_n,
                [Validators.required, Validators.min(1), Validators.max(10)],
            ],
            local_search_llm_max_gen_tokens: [
                configs?.local_search_llm_max_gen_tokens ?? GRAPH_DRIFT_DEFAULTS.local_search_llm_max_gen_tokens,
            ],
            local_search_llm_max_gen_completion_tokens: [
                configs?.local_search_llm_max_gen_completion_tokens ??
                    GRAPH_DRIFT_DEFAULTS.local_search_llm_max_gen_completion_tokens,
            ],
            community_level: [configs?.community_level ?? GRAPH_DRIFT_DEFAULTS.community_level],
        });
    }

    private wireDynamicCommunityToggle(): void {
        const globalGroup = this.searchConfigsFormGroup?.get('global_search') as FormGroup | null;
        if (!globalGroup) return;
        const flag = globalGroup.get('dynamic_community_selection');
        if (!flag) return;

        const toggle = (enabled: boolean) => {
            const dependents = [
                'dynamic_search_threshold',
                'dynamic_search_keep_parent',
                'dynamic_search_num_repeats',
                'dynamic_search_use_summary',
                'dynamic_search_max_level',
            ];
            dependents.forEach((name) => {
                const ctrl = globalGroup.get(name);
                if (!ctrl) return;
                if (enabled) {
                    ctrl.enable({ emitEvent: false });
                } else {
                    ctrl.disable({ emitEvent: false });
                }
            });
        };

        toggle(!!flag.value);
        flag.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((v) => toggle(!!v));
    }

    onTextUnitPropUpdate(value: number): void {
        this.textUnitProportionControl.setValue(value);
    }

    onCommunityPropUpdate(value: number): void {
        this.communityProportionControl.setValue(value);
    }

    onDriftLocalTextUnitPropUpdate(value: number): void {
        this.driftLocalTextUnitPropControl.setValue(value);
    }

    onDriftLocalCommunityPropUpdate(value: number): void {
        this.driftLocalCommunityPropControl.setValue(value);
    }

    isKnowledgeControlInvalid(): boolean {
        return !!this.form().get('knowledge_collection')?.invalid;
    }

    isRagControlInvalid(): boolean {
        return !!this.form().get('rag')?.invalid;
    }

    get collectionId(): number | null {
        return this.form().get('knowledge_collection')?.value ?? null;
    }

    get activeGraphMethod(): GraphSearchMethod | null {
        return (this.searchConfigsFormGroup?.get('search_method')?.value as GraphSearchMethod) ?? null;
    }

    canToggleSuggested(): boolean {
        if (this.llmConfigId() == null) return false;
        if (this.collectionId == null) return false;
        if (this.selectedRagType() === 'graph' && !this.activeGraphMethod) return false;
        return !!this.searchConfigsFormGroup;
    }

    lockReason(): string {
        return 'Assign an LLM to this agent so we know which model will run these searches.';
    }

    applySuggestedParams(): void {
        if (!this.canToggleSuggested()) return;
        this.suggestErrorFor.set(null);
        this.fetchAndApply(this.activeKey());
    }

    private fetchAndApply(key: SuggestKey): void {
        const collectionId = this.collectionId;
        const llmConfigId = this.llmConfigId();
        if (collectionId == null || llmConfigId == null) {
            return;
        }

        this.suggestingFor.set(key);
        this.suggestErrorFor.set(null);

        const request$ =
            key === 'naive'
                ? this.agentsService.suggestNaiveSearchParams({
                      knowledge_collection_id: collectionId,
                      llm_config_id: llmConfigId,
                  })
                : this.agentsService.suggestGraphSearchParams({
                      knowledge_collection_id: collectionId,
                      llm_config_id: llmConfigId,
                      search_method: key,
                  });

        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (response) => this.applyResponse(key, response),
            error: () => {
                this.suggestErrorFor.set(key);
                this.suggestingFor.set(null);
            },
        });
    }

    private applyResponse(key: SuggestKey, response: SuggestResponse): void {
        const target =
            key === 'naive' ? this.searchConfigsFormGroup : (this.searchConfigsFormGroup?.get(key) as FormGroup | null);
        if (!target) {
            this.suggestingFor.set(null);
            return;
        }

        target.patchValue(response.suggested_params, { emitEvent: false });
        target.markAsPristine();

        if (key !== 'naive' && response.recommended_search_method) {
            this.recommendedSearchMethod.set(response.recommended_search_method);
        }
        this.suggestingFor.set(null);
    }

    retryMetadataFetch(): void {
        this.tokenLimitsError.set(null);
        this.lastRecommendationKey = null;
        this.maybeFetchSearchMetadata();
    }

    private maybeFetchSearchMetadata(): void {
        if (!this.featureAvailable()) return;
        const collectionId = this.collectionId;
        const llmConfigId = this.llmConfigId();
        const ragType = this.selectedRagType();
        if (collectionId == null || llmConfigId == null || !ragType) return;
        if (!this.searchConfigsFormGroup) return;
        if (ragType === 'graph' && !this.activeGraphMethod) return;

        const method = (this.activeGraphMethodSignal() ?? 'basic') as GraphSearchMethod;
        const key = `${collectionId}|${llmConfigId}|${ragType}|${ragType === 'graph' ? method : 'naive'}`;

        const cached = this.tokenLimitsCache.get(llmConfigId);
        if (cached) {
            this.effectiveLlmContextWindow.set(cached.ctx);
            this.safeTokenBudget.set(cached.safe);
            this.tokenLimitsLoading.set(false);
            this.tokenLimitsError.set(null);
            this.refreshTokenValidators();
        }

        if (this.lastRecommendationKey === key) return;
        this.lastRecommendationKey = key;

        if (!cached) {
            this.tokenLimitsLoading.set(true);
            this.tokenLimitsError.set(null);
        }

        const token = ++this.fetchToken;
        const request$ =
            ragType === 'naive'
                ? this.agentsService.suggestNaiveSearchParams({
                      knowledge_collection_id: collectionId,
                      llm_config_id: llmConfigId,
                  })
                : this.agentsService.suggestGraphSearchParams({
                      knowledge_collection_id: collectionId,
                      llm_config_id: llmConfigId,
                      search_method: method,
                  });

        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (response) => {
                if (token !== this.fetchToken) return;
                this.tokenLimitsCache.set(llmConfigId, {
                    ctx: response.effective_llm_context_window,
                    safe: response.safe_token_budget,
                });
                this.effectiveLlmContextWindow.set(response.effective_llm_context_window);
                this.safeTokenBudget.set(response.safe_token_budget);
                this.tokenLimitsLoading.set(false);
                this.tokenLimitsError.set(null);
                if (ragType === 'graph' && response.recommended_search_method) {
                    this.recommendedSearchMethod.set(response.recommended_search_method);
                }
                this.refreshTokenValidators();
            },
            error: () => {
                if (token !== this.fetchToken) return;
                this.tokenLimitsLoading.set(false);
                this.tokenLimitsError.set(
                    "Couldn't load token limits for this LLM. Check your connection and try again."
                );
                this.lastRecommendationKey = null;
            },
        });
    }

    private refreshTokenValidators(): void {
        const ctx = this.effectiveLlmContextWindow();
        const group = this.searchConfigsFormGroup;
        if (ctx == null || !group) return;

        const tokenFieldsByMethod: Record<string, { name: string; min: number; required: boolean }[]> = {
            basic: [{ name: 'max_context_tokens', min: 100, required: true }],
            local: [{ name: 'max_context_tokens', min: 100, required: true }],
            global_search: [
                { name: 'max_context_tokens', min: 100, required: true },
                { name: 'data_max_tokens', min: 100, required: true },
            ],
            drift_search: [
                { name: 'data_max_tokens', min: 100, required: true },
                { name: 'primer_llm_max_tokens', min: 100, required: true },
                { name: 'local_search_max_data_tokens', min: 100, required: true },
                { name: 'reduce_max_tokens', min: 1, required: false },
                { name: 'reduce_max_completion_tokens', min: 1, required: false },
                { name: 'local_search_llm_max_gen_tokens', min: 1, required: false },
                { name: 'local_search_llm_max_gen_completion_tokens', min: 1, required: false },
            ],
        };

        for (const method of ['basic', 'local', 'global_search', 'drift_search']) {
            const methodGroup = group.get(method) as FormGroup | null;
            if (!methodGroup) continue;
            for (const field of tokenFieldsByMethod[method]) {
                const ctrl = methodGroup.get(field.name);
                if (!ctrl) continue;
                const validators = [Validators.min(field.min), Validators.max(ctx)];
                if (field.required) validators.unshift(Validators.required);
                ctrl.setValidators(validators);
                ctrl.updateValueAndValidity({ emitEvent: false });
            }
        }
    }

    private resetSuggestState(): void {
        this.suggestingFor.set(null);
        this.suggestErrorFor.set(null);
        this.recommendedSearchMethod.set(null);
        this.lastRecommendationKey = null;
    }
}
