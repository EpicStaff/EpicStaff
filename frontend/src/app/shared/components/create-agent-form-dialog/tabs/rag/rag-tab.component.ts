import { NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
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
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    DualSliderComponent,
    InputNumberComponent,
    KnowledgeSelectorComponent,
    RadioButtonComponent,
    RagSelectorComponent,
    SelectItem,
    SliderWithStepperComponent,
    SuggestedValueComponent,
    TextareaComponent,
    ToggleSwitchComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { Subscription } from 'rxjs';

import {
    GetCollectionRagsResponse,
    GetCollectionRequest,
} from '../../../../../features/knowledge-sources/models/collection.model';
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
import { TooltipComponent } from '../../../tooltip/tooltip.component';

type SuggestKey = GraphSearchMethod | 'naive';

const PROMPT_FIELDS: Record<SuggestKey, string[]> = {
    naive: [],
    basic: ['prompt'],
    local: ['prompt'],
    global: ['map_prompt', 'reduce_prompt', 'knowledge_prompt'],
    drift: ['prompt', 'reduce_prompt'],
};

// Fields that stay editable while "Use Suggested Params" is on — editing them
// doesn't turn the toggle off. Instead they anchor a recompute: the user can
// dial in a target value, then re-request suggestions constrained to it via
// user_custom_params (see onApplyMaxContextTokens).
type AnchorKey = 'basic' | 'local' | 'global' | 'drift';

// Drift has no max_context_tokens field of its own — data_max_tokens plays
// that role in its UI. Whatever the form control is called, the backend's
// anchor key in user_custom_params is always literally "max_context_tokens".
const ANCHOR_FIELD_NAME: Record<AnchorKey, string> = {
    basic: 'max_context_tokens',
    local: 'max_context_tokens',
    global: 'max_context_tokens',
    drift: 'data_max_tokens',
};

// Drift's 4 advanced token caps (reduce_*, local_search_llm_max_gen_*) are
// never recalculated from the anchor — the backend only clamps them as a
// ceiling if they're ever sent above budget. They stay editable at all times,
// capped in the UI by the live Data Max Tokens value, so they're exempt from
// the toggle-off diff for the same reason the anchor field itself is.
const DRIFT_ALWAYS_EDITABLE_FIELDS = [
    'reduce_max_tokens',
    'reduce_max_completion_tokens',
    'local_search_llm_max_gen_tokens',
    'local_search_llm_max_gen_completion_tokens',
];

const ANCHOR_FIELDS: Partial<Record<SuggestKey, string[]>> = {
    basic: [ANCHOR_FIELD_NAME.basic],
    local: [ANCHOR_FIELD_NAME.local],
    global: [ANCHOR_FIELD_NAME.global],
    drift: [ANCHOR_FIELD_NAME.drift, ...DRIFT_ALWAYS_EDITABLE_FIELDS],
};

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
    community_level: 2,
    local_search_text_unit_prop: 0.9,
    local_search_community_prop: 0.1,
    local_search_top_k_mapped_entities: 10,
    local_search_top_k_relationships: 10,
    local_search_max_data_tokens: 12000,
    local_search_top_p: 1.0,
    local_search_n: 1,
    local_search_llm_max_gen_tokens: null,
    local_search_llm_max_gen_completion_tokens: null,
};

@Component({
    selector: 'app-rag-tab',
    templateUrl: './rag-tab.component.html',
    styleUrls: ['../tab.component.scss'],
    imports: [
        ReactiveFormsModule,
        MatTooltipModule,
        NgTemplateOutlet,
        KnowledgeSelectorComponent,
        RagSelectorComponent,
        SliderWithStepperComponent,
        RadioButtonComponent,
        InputNumberComponent,
        DualSliderComponent,
        TextareaComponent,
        ValidationErrorsComponent,
        ToggleSwitchComponent,
        AppSvgIconComponent,
        SuggestedValueComponent,
        TooltipComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RagTabComponent implements OnInit {
    private fb = inject(FormBuilder);
    private destroyRef = inject(DestroyRef);
    private agentsService = inject(AgentsService);
    private cdr = inject(ChangeDetectorRef);

    form = input.required<FormGroup>();
    allKnowledgeSources = input.required<GetCollectionRequest[]>();
    agentRags = input.required<GetCollectionRagsResponse[]>();
    searchConfigs = input.required<AgentSearchConfigs | null>();
    loadingKnowledgeSources = input<boolean>(false);
    loadingRags = input<boolean>(false);
    llmConfigId = input<number | null>(null);
    // When embedded in a host that already has its own collection/rag-kind
    // picker (e.g. the Surface knowledge-advanced panel), hide this tab's own
    // "Select Knowledge Source"/"Select Agent Rags" UI so the two don't duplicate.
    hideSourceSelectors = input<boolean>(false);
    readOnly = input<boolean>(false);

    selectedRagType = signal<'naive' | 'graph' | null>(null);
    activeGraphMethodSignal = signal<GraphSearchMethod | null>(null);
    globalAdvancedOpen = signal<boolean>(false);
    driftAdvancedOpen = signal<boolean>(false);
    recommendedSearchMethod = signal<GraphSearchMethod | null>(null);
    suggestingFor = signal<SuggestKey | null>(null);
    suggestErrorFor = signal<SuggestKey | null>(null);
    useSuggestedParams = signal<boolean>(false);
    private searchConfigsValueChangesSub: Subscription | null = null;
    private dynamicCommunityToggleSub: Subscription | null = null;
    private driftDataMaxTokensCapSub: Subscription | null = null;
    // Baseline the "did the user edit a non-prompt field" diff runs against.
    // Must be resynced after every programmatic patch (applyResponse) — otherwise
    // the very next value-change event, even one caused solely by typing in a
    // prompt field, would diff against a pre-patch baseline and see the
    // suggested params' own K/token/etc. changes as if the user had just made
    // them, incorrectly turning the toggle back off.
    private lastNonPromptSnapshot: string | null = null;

    featureAvailable = computed<boolean>(() => this.llmConfigId() != null);

    tokenLimitsLoading = signal<boolean>(false);
    tokenLimitsError = signal<string | null>(null);
    effectiveLlmContextWindow = signal<number | null>(null);
    // safe_token_budget is default_budget from the backend — it depends on
    // whatever max_context_tokens anchor was last submitted for THAT specific
    // method, so unlike effectiveLlmContextWindow (a true LLM-level constant)
    // it must be tracked per method. A single shared signal here previously
    // leaked one method's custom budget into every other method's warning/max.
    private safeTokenBudgetByKey = signal<Partial<Record<SuggestKey, number>>>({});

    safeTokenBudget = computed<number | null>(() => this.safeTokenBudgetByKey()[this.activeKey()] ?? null);

    private baselineSafeTokenBudgetByKey = signal<Partial<Record<SuggestKey, number>>>({});

    baselineSafeTokenBudget = computed<number | null>(
        () => this.baselineSafeTokenBudgetByKey()[this.activeKey()] ?? null
    );

    private setSafeTokenBudget(key: SuggestKey, value: number, isCustomAnchor = false): void {
        this.safeTokenBudgetByKey.update((map) => ({ ...map, [key]: value }));
        if (!isCustomAnchor) {
            this.baselineSafeTokenBudgetByKey.update((map) => ({ ...map, [key]: value }));
        }
    }

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

    baselineTokenWarningMsg = computed<string>(() => {
        const safe = this.baselineSafeTokenBudget();
        return safe != null ? `Above recommended budget (${safe.toLocaleString()} tokens).` : '';
    });

    // Paired with [min]="100" on every field that binds this message (the anchor
    // field and its "Data Max Tokens" siblings) — isOutOfRange() in app-input-number
    // fires this for either bound, so the text must describe both, not just the max.
    tokenErrorMsg = computed<string>(() => {
        const ctx = this.effectiveLlmContextWindow();
        return ctx != null ? `Must be between 100 and ${ctx.toLocaleString()} tokens.` : '';
    });

    // Cache the LLM's context window per llm_config_id — this is a true LLM-level
    // constant, safe to share across methods. safe_token_budget is NOT cached here
    // (see safeTokenBudgetByKey above) since it depends on the per-method anchor.
    private tokenLimitsCache = new Map<number, { ctx: number }>();
    // Cache full suggest responses per (collection, llm, ragType, method) so opting
    // into "Use Suggested Params" right after the background metadata fetch already
    // ran doesn't fire a second, identical request to the same endpoint.
    private suggestResponseCache = new Map<string, SuggestResponse>();
    private fetchToken = 0;
    private lastLlmConfigId: number | null = null;

    // Guard so the initial recommendation fetch fires once per
    // (collection, llm, ragType) triple, not on every signal touch.
    private lastRecommendationKey: string | null = null;

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
                value: 'global',
                icon: rec === 'global' ? 'star' : undefined,
                tooltip: rec === 'global' ? recTooltip : undefined,
            },
            {
                name: 'DRIFT',
                value: 'drift',
                icon: rec === 'drift' ? 'star' : undefined,
                tooltip: rec === 'drift' ? recTooltip : undefined,
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
                this.cdr.markForCheck();
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

        // No explicit "first mount" fetch here: the constructor's llmConfigId
        // effect always runs at least once on creation (lastLlmConfigId starts
        // null), so it already covers "everything's already there on mount" —
        // a second explicit call here would just be a duplicate trigger for the
        // exact same fetch.
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
                is_suggested: [!!configs?.naive?.is_suggested],
            });
            this.useSuggestedParams.set(!!configs?.naive?.is_suggested);
        }

        if (ragType === 'graph') {
            const initialMethod = (configs?.graph?.search_method ?? 'basic') as GraphSearchMethod;
            this.searchConfigsFormGroup = this.fb.group({
                search_method: [initialMethod, [Validators.required]],
                basic: this.initGraphBasicSearchConfig(configs?.graph?.basic),
                local: this.initGraphLocalSearchConfig(configs?.graph?.local),
                global: this.initGraphGlobalSearchConfig(configs?.graph?.global),
                drift: this.initGraphDriftSearchConfig(configs?.graph?.drift),
            });
            this.activeGraphMethodSignal.set(initialMethod);
            this.useSuggestedParams.set(!!this.searchConfigsFormGroup.get(initialMethod)?.get('is_suggested')?.value);
            this.searchConfigsFormGroup
                .get('search_method')
                ?.valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((m) => {
                    this.activeGraphMethodSignal.set((m as GraphSearchMethod) ?? null);
                    // Drop interest in whatever suggestion request was in flight for the
                    // method we just left — otherwise a slow response could land later and
                    // silently patch a subgroup the user can no longer see.
                    this.suggestingFor.set(null);
                    this.suggestErrorFor.set(null);
                    this.useSuggestedParams.set(!!this.searchConfigsFormGroup?.get(m)?.get('is_suggested')?.value);
                });

            this.wireDynamicCommunityToggle();
            this.wireDriftDataMaxTokensCap();
        } else {
            this.activeGraphMethodSignal.set(null);
        }

        if (this.readOnly()) this.searchConfigsFormGroup?.disable({ emitEvent: false });

        // emitEvent:false — this runs on every mount/rebuild (e.g. switching collection
        // tabs in surface-knowledge-advanced), not just on a real user edit. Without it,
        // callers debouncing the parent form's valueChanges (to autosave) fire a save
        // the instant this control is attached, before the user has touched anything.
        this.form().setControl('search_configs', this.searchConfigsFormGroup, { emitEvent: false });

        // A genuine user edit to a suggested field (or switching search_method)
        // should turn the "use suggested params" toggle back off. Prompt fields
        // are excluded — they're never part of what the toggle applies (see
        // PROMPT_FIELDS), so editing them shouldn't disable it either.
        // applyResponse() below always patches with { emitEvent: false }, and
        // Angular threads that flag up through every ancestor's own
        // valueChanges — so this only fires for real user edits, never for our
        // own programmatic patch.
        this.searchConfigsValueChangesSub?.unsubscribe();
        this.syncNonPromptSnapshot();
        this.searchConfigsValueChangesSub = this.searchConfigsFormGroup!.valueChanges.pipe(
            takeUntilDestroyed(this.destroyRef)
        ).subscribe((value) => {
            const snapshot = JSON.stringify(this.withoutPromptFields(value));
            if (snapshot === this.lastNonPromptSnapshot) return;
            this.lastNonPromptSnapshot = snapshot;
            this.useSuggestedParams.set(false);
            this.syncSuggestedFlagToActiveTarget(false);
        });

        this.cdr.markForCheck();
    }

    // Call after any programmatic patch, or the next real edit's diff would
    // run against a pre-patch baseline.
    private syncNonPromptSnapshot(): void {
        if (!this.searchConfigsFormGroup) return;
        this.lastNonPromptSnapshot = JSON.stringify(this.withoutPromptFields(this.searchConfigsFormGroup.value));
    }

    private withoutPromptFields(value: unknown): Record<string, unknown> {
        const clone: Record<string, unknown> = { ...(value as Record<string, unknown>) };
        delete clone['is_suggested'];
        delete clone['search_method'];
        for (const method of ['basic', 'local', 'global', 'drift'] as const) {
            const sub = clone[method];
            if (!sub || typeof sub !== 'object') continue;
            const subClone: Record<string, unknown> = { ...(sub as Record<string, unknown>) };
            for (const field of [...PROMPT_FIELDS[method], ...(ANCHOR_FIELDS[method] ?? [])]) {
                delete subClone[field];
            }
            delete subClone['is_suggested'];
            clone[method] = subClone;
        }
        return clone;
    }

    private initGraphBasicSearchConfig(configs: GraphBasicSearchConfig | undefined): FormGroup {
        return this.fb.group({
            prompt: [configs?.prompt ?? GRAPH_BASIC_DEFAULTS.prompt, [Validators.maxLength(1000)]],
            k: [configs?.k ?? GRAPH_BASIC_DEFAULTS.k, [Validators.required, Validators.min(1), Validators.max(100)]],
            max_context_tokens: [
                configs?.max_context_tokens ?? GRAPH_BASIC_DEFAULTS.max_context_tokens,
                [Validators.required, Validators.min(100), Validators.max(100000)],
            ],
            is_suggested: [!!configs?.is_suggested],
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
            is_suggested: [!!configs?.is_suggested],
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
                [Validators.required, Validators.min(0)],
            ],
            dynamic_search_keep_parent: [
                configs?.dynamic_search_keep_parent ?? GRAPH_GLOBAL_DEFAULTS.dynamic_search_keep_parent,
            ],
            dynamic_search_num_repeats: [
                configs?.dynamic_search_num_repeats ?? GRAPH_GLOBAL_DEFAULTS.dynamic_search_num_repeats,
                [Validators.required, Validators.min(1)],
            ],
            dynamic_search_use_summary: [
                configs?.dynamic_search_use_summary ?? GRAPH_GLOBAL_DEFAULTS.dynamic_search_use_summary,
            ],
            dynamic_search_max_level: [
                configs?.dynamic_search_max_level ?? GRAPH_GLOBAL_DEFAULTS.dynamic_search_max_level,
                [Validators.required, Validators.min(0), Validators.max(10)],
            ],
            is_suggested: [!!configs?.is_suggested],
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
            reduce_max_tokens: [
                configs?.reduce_max_tokens ?? GRAPH_DRIFT_DEFAULTS.reduce_max_tokens,
                [Validators.min(1), Validators.max(100000)],
            ],
            reduce_max_completion_tokens: [
                configs?.reduce_max_completion_tokens ?? GRAPH_DRIFT_DEFAULTS.reduce_max_completion_tokens,
                [Validators.min(1), Validators.max(100000)],
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
                [Validators.required, Validators.min(1), Validators.max(100)],
            ],
            primer_llm_max_tokens: [
                configs?.primer_llm_max_tokens ?? GRAPH_DRIFT_DEFAULTS.primer_llm_max_tokens,
                [Validators.required, Validators.min(100), Validators.max(100000)],
            ],
            n_depth: [
                configs?.n_depth ?? GRAPH_DRIFT_DEFAULTS.n_depth,
                [Validators.required, Validators.min(1), Validators.max(10)],
            ],
            community_level: [
                configs?.community_level ?? GRAPH_DRIFT_DEFAULTS.community_level,
                [Validators.min(0), Validators.max(10)],
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
                [Validators.min(1), Validators.max(100000)],
            ],
            local_search_llm_max_gen_completion_tokens: [
                configs?.local_search_llm_max_gen_completion_tokens ??
                    GRAPH_DRIFT_DEFAULTS.local_search_llm_max_gen_completion_tokens,
                [Validators.min(1), Validators.max(100000)],
            ],
            is_suggested: [!!configs?.is_suggested],
        });
    }

    // Reduce Max Tokens / Reduce Max Completion Tokens / Local LLM Max Gen (Completion)
    // Tokens are capped by the live Data Max Tokens value (see refreshTokenValidators).
    // Their real Validators.max only gets recomputed on suggest responses (applyResponse
    // calls refreshTokenValidators) — this covers the user typing into Data Max Tokens
    // directly, without ever touching "Use Suggested Params".
    private wireDriftDataMaxTokensCap(): void {
        // initSearchConfigsFormGroup() rebuilds searchConfigsFormGroup (and this
        // control) on every rag-kind/search_method switch — unsubscribe the
        // previous wiring first, or takeUntilDestroyed(this.destroyRef) would keep
        // it alive (subscribed to an abandoned form) until the component itself
        // is destroyed, accumulating one leaked subscription per switch.
        this.driftDataMaxTokensCapSub?.unsubscribe();
        const driftGroup = this.searchConfigsFormGroup?.get('drift') as FormGroup | null;
        const dataMaxTokensControl = driftGroup?.get('data_max_tokens');
        if (!dataMaxTokensControl) return;
        this.driftDataMaxTokensCapSub = dataMaxTokensControl.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.refreshTokenValidators());
    }

    private wireDynamicCommunityToggle(): void {
        // Same reason as wireDriftDataMaxTokensCap above.
        this.dynamicCommunityToggleSub?.unsubscribe();
        const globalGroup = this.searchConfigsFormGroup?.get('global') as FormGroup | null;
        if (!globalGroup) return;
        const flag = globalGroup.get('dynamic_community_selection');
        if (!flag) return;

        this.syncDynamicCommunityDependents(!!flag.value);
        this.dynamicCommunityToggleSub = flag.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((v) => this.syncDynamicCommunityDependents(!!v));
    }

    // Also called from applyResponse(): a suggested-params patch sets
    // dynamic_community_selection with { emitEvent: false }, which never fires
    // the valueChanges subscription above, so without this the dependents'
    // enabled state would go stale relative to the newly-suggested value.
    private syncDynamicCommunityDependents(enabled: boolean): void {
        const globalGroup = this.searchConfigsFormGroup?.get('global') as FormGroup | null;
        if (!globalGroup) return;
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

    get basicGroup(): FormGroup | null {
        return (this.searchConfigsFormGroup?.get('basic') as FormGroup | null) ?? null;
    }

    get localGroup(): FormGroup | null {
        return (this.searchConfigsFormGroup?.get('local') as FormGroup | null) ?? null;
    }

    get globalGroup(): FormGroup | null {
        return (this.searchConfigsFormGroup?.get('global') as FormGroup | null) ?? null;
    }

    get driftGroup(): FormGroup | null {
        return (this.searchConfigsFormGroup?.get('drift') as FormGroup | null) ?? null;
    }

    get driftDataMaxTokensCapMessage(): string {
        const cap = this.driftGroup?.get('data_max_tokens')?.value;
        return typeof cap === 'number' ? `Can't exceed Data Max Tokens (${cap.toLocaleString()}).` : '';
    }

    get anchorFieldLabel(): string {
        return this.activeGraphMethod === 'drift' ? 'Data Max Tokens' : 'Max Context Tokens';
    }

    get anchorFieldTooltip(): string {
        return this.activeGraphMethod === 'drift'
            ? 'Token limit for the data stage.'
            : 'The maximum context size to create, in tokens';
    }

    get activeMaxContextTokensControl(): FormControl | null {
        const key = this.activeGraphMethod;
        if (!this.isAnchorKey(key)) return null;
        const group =
            key === 'basic'
                ? this.basicGroup
                : key === 'local'
                  ? this.localGroup
                  : key === 'global'
                    ? this.globalGroup
                    : this.driftGroup;
        return (group?.get(ANCHOR_FIELD_NAME[key]) as FormControl | null) ?? null;
    }

    // Last suggested anchor-field value applied per method — the "Apply" button
    // next to the field is only enabled once the live value drifts from this.
    private lastSuggestedMaxContextTokens = new Map<AnchorKey, number>();

    private isAnchorKey(key: SuggestKey | null): key is AnchorKey {
        return key === 'basic' || key === 'local' || key === 'global' || key === 'drift';
    }

    maxContextTokensDirty(): boolean {
        const key = this.activeGraphMethod;
        if (!this.isAnchorKey(key)) return false;
        const current = this.activeMaxContextTokensControl?.value;
        const baseline = this.lastSuggestedMaxContextTokens.get(key);
        return baseline != null && current != null && current !== baseline;
    }

    onApplyMaxContextTokens(): void {
        const key = this.activeGraphMethod;
        if (!this.isAnchorKey(key)) return;
        if (this.suggestingFor() === key) return;

        const collectionId = this.collectionId;
        const llmConfigId = this.llmConfigId();
        const value = this.activeMaxContextTokensControl?.value;
        if (collectionId == null || llmConfigId == null || value == null) return;

        this.suggestingFor.set(key);
        this.suggestErrorFor.set(null);

        // A monotonic token, not just the suggestingFor key, guards against a
        // stale response winning a race: switching away-and-back to the same
        // method (or firing Apply twice) reuses the same key, so an in-flight
        // earlier request could otherwise still land after a newer one.
        const token = ++this.fetchToken;

        this.agentsService
            .suggestGraphSearchParams({
                knowledge_collection_id: collectionId,
                llm_config_id: llmConfigId,
                search_method: key,
                user_custom_params: { max_context_tokens: value },
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (response) => {
                    if (token !== this.fetchToken || this.suggestingFor() !== key) return;
                    // Deliberately NOT written to suggestResponseCache — that cache is keyed
                    // only by (collection, llm, ragType, method), with no room for the custom
                    // anchor value. Caching a customized response there would make a later
                    // plain toggle-off/on for this method silently replay this override
                    // instead of fetching the neutral default suggestion.
                    this.applyResponse(key, response, llmConfigId, true);
                },
                error: () => {
                    if (token !== this.fetchToken || this.suggestingFor() !== key) return;
                    this.suggestingFor.set(null);
                    this.suggestErrorFor.set(key);
                },
            });
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

    onSuggestedParamsToggle(checked: boolean): void {
        if (!this.canToggleSuggested()) {
            this.useSuggestedParams.set(false);
            return;
        }
        this.useSuggestedParams.set(checked);
        this.syncSuggestedFlagToActiveTarget(checked);
        if (checked) {
            this.suggestErrorFor.set(null);
            this.fetchAndApply(this.activeKey());
        }
    }

    private fetchAndApply(key: SuggestKey): void {
        const collectionId = this.collectionId;
        const llmConfigId = this.llmConfigId();
        if (collectionId == null || llmConfigId == null) {
            return;
        }

        const cacheKey = this.metadataKeyFor(key);
        const cachedResponse = cacheKey ? this.suggestResponseCache.get(cacheKey) : undefined;
        if (cachedResponse) {
            this.applyResponse(key, cachedResponse, llmConfigId);
            return;
        }

        this.suggestingFor.set(key);
        this.suggestErrorFor.set(null);

        // See onApplyMaxContextTokens for why a request token (not just the
        // suggestingFor key) is needed to reject a stale response.
        const token = ++this.fetchToken;

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
            next: (response) => {
                // A newer fetchAndApply call (for a different key, or a repeat of
                // this same key) may have already overwritten suggestingFor/token —
                // ignore this stale response so it can't stomp on a currently-active
                // or already-superseded request.
                if (token !== this.fetchToken || this.suggestingFor() !== key) return;
                this.applyResponse(key, response, llmConfigId);
            },
            error: () => {
                if (token !== this.fetchToken || this.suggestingFor() !== key) return;
                this.suggestErrorFor.set(key);
                this.suggestingFor.set(null);
                this.useSuggestedParams.set(false);
                this.syncSuggestedFlagToActiveTarget(false);
            },
        });
    }

    private applyResponse(
        key: SuggestKey,
        response: SuggestResponse,
        requestLlmConfigId: number | null,
        isCustomAnchor = false
    ): void {
        const target =
            key === 'naive' ? this.searchConfigsFormGroup : (this.searchConfigsFormGroup?.get(key) as FormGroup | null);
        if (!target) {
            this.suggestingFor.set(null);
            return;
        }

        const params = { ...response.suggested_params };
        for (const field of PROMPT_FIELDS[key]) {
            delete params[field];
        }
        if (this.isAnchorKey(key)) {
            const anchorValue = params[ANCHOR_FIELD_NAME[key]];
            if (typeof anchorValue === 'number') this.lastSuggestedMaxContextTokens.set(key, anchorValue);
            const fieldsToExclude = isCustomAnchor
                ? (ANCHOR_FIELDS[key] ?? [])
                : key === 'drift'
                  ? DRIFT_ALWAYS_EDITABLE_FIELDS
                  : [];
            for (const field of fieldsToExclude) {
                delete params[field];
            }
        }
        target.patchValue(params, { emitEvent: false });
        target.get('is_suggested')?.setValue(true, { emitEvent: false });
        target.markAsPristine();
        // safe_token_budget reflects default_budget, which shifts with whatever
        // max_context_tokens anchor was just submitted — refresh it (and the
        // llm-keyed cache) so other fields' warningMax/tokenErrorMsg stay in
        // sync with the budget this very response was computed against.
        this.effectiveLlmContextWindow.set(response.effective_llm_context_window);
        this.setSafeTokenBudget(key, response.safe_token_budget, isCustomAnchor);
        // Cache under the llmConfigId the REQUEST was made for, not whatever
        // this.llmConfigId() reads now — if the user switched LLMs while this
        // request was in flight, those would differ and this response's window
        // would otherwise poison the cache entry for the new LLM.
        if (requestLlmConfigId != null) {
            this.tokenLimitsCache.set(requestLlmConfigId, { ctx: response.effective_llm_context_window });
        }
        if (key === 'global') {
            this.syncDynamicCommunityDependents(!!this.globalGroup?.get('dynamic_community_selection')?.value);
        }
        // Drift's always-editable fields are capped by the live data_max_tokens
        // value (see refreshTokenValidators) — that value just changed above.
        this.refreshTokenValidators();
        // The patch above never emits, so the next value-change event (even a
        // harmless prompt edit) would otherwise diff against a pre-patch
        // baseline and see this patch's own field changes as a user edit.
        this.syncNonPromptSnapshot();

        if (key !== 'naive' && response.recommended_search_method) {
            this.recommendedSearchMethod.set(response.recommended_search_method);
        }
        this.suggestingFor.set(null);
    }

    private metadataKeyFor(key: SuggestKey): string | null {
        const collectionId = this.collectionId;
        const llmConfigId = this.llmConfigId();
        if (collectionId == null || llmConfigId == null) return null;
        const ragType = key === 'naive' ? 'naive' : 'graph';
        return `${collectionId}|${llmConfigId}|${ragType}|${key}`;
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
        const suggestKey: SuggestKey = ragType === 'graph' ? method : 'naive';
        const key = this.metadataKeyFor(suggestKey);
        if (!key) return;

        const cached = this.tokenLimitsCache.get(llmConfigId);
        const cachedResponse = this.suggestResponseCache.get(key);
        if (cached) {
            this.effectiveLlmContextWindow.set(cached.ctx);
            if (cachedResponse) this.setSafeTokenBudget(suggestKey, cachedResponse.safe_token_budget);
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
                this.tokenLimitsCache.set(llmConfigId, { ctx: response.effective_llm_context_window });
                this.suggestResponseCache.set(key, response);
                this.effectiveLlmContextWindow.set(response.effective_llm_context_window);
                this.setSafeTokenBudget(suggestKey, response.safe_token_budget);
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

        const tokenFieldsByMethod: Record<
            string,
            { name: string; min: number; required: boolean; cappedByDataMaxTokens?: boolean }[]
        > = {
            basic: [{ name: 'max_context_tokens', min: 100, required: true }],
            local: [{ name: 'max_context_tokens', min: 100, required: true }],
            global: [
                { name: 'max_context_tokens', min: 100, required: true },
                { name: 'data_max_tokens', min: 100, required: true },
            ],
            drift: [
                { name: 'data_max_tokens', min: 100, required: true },
                { name: 'primer_llm_max_tokens', min: 100, required: true },
                { name: 'local_search_max_data_tokens', min: 100, required: true },
                { name: 'reduce_max_tokens', min: 1, required: false, cappedByDataMaxTokens: true },
                { name: 'reduce_max_completion_tokens', min: 1, required: false, cappedByDataMaxTokens: true },
                { name: 'local_search_llm_max_gen_tokens', min: 1, required: false, cappedByDataMaxTokens: true },
                {
                    name: 'local_search_llm_max_gen_completion_tokens',
                    min: 1,
                    required: false,
                    cappedByDataMaxTokens: true,
                },
            ],
        };

        for (const method of ['basic', 'local', 'global', 'drift']) {
            const methodGroup = group.get(method) as FormGroup | null;
            if (!methodGroup) continue;
            for (const field of tokenFieldsByMethod[method]) {
                const ctrl = methodGroup.get(field.name);
                if (!ctrl) continue;
                // These are never derived from the anchor — the UI caps them to
                // Data Max Tokens (see driftDataMaxTokensCapMessage), so the real
                // validator must match that, not the LLM's full context window.
                const dataMaxTokens = field.cappedByDataMaxTokens ? methodGroup.get('data_max_tokens')?.value : null;
                const max = typeof dataMaxTokens === 'number' ? Math.min(ctx, dataMaxTokens) : ctx;
                const validators = [Validators.min(field.min), Validators.max(max)];
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
        this.useSuggestedParams.set(false);
        this.syncSuggestedFlagToActiveTarget(false);
        this.lastRecommendationKey = null;
    }

    private syncSuggestedFlagToActiveTarget(value: boolean): void {
        const key = this.activeKey();
        const target =
            key === 'naive' ? this.searchConfigsFormGroup : (this.searchConfigsFormGroup?.get(key) as FormGroup | null);
        target?.get('is_suggested')?.setValue(value, { emitEvent: false });
    }
}
