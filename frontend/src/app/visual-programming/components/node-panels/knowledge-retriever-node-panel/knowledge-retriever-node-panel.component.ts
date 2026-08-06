import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    CustomInputComponent,
    DualSliderComponent,
    InputNumberComponent,
    RadioButtonComponent,
    SelectComponent,
    SelectItem,
    SliderWithStepperComponent,
    TextareaComponent,
} from '@shared/components';
import {
    AgentSearchConfigs,
    GraphBasicSearchConfig,
    GraphLocalSearchConfig,
    GraphSearchMethod,
    NaiveRagSearchConfig,
} from '@shared/models';
import { Subject } from 'rxjs';
import { debounceTime } from 'rxjs/operators';

import {
    GetCollectionRagsResponse,
    GetCollectionRequest,
} from '../../../../features/knowledge-sources/models/collection.model';
import { CollectionsApiService } from '../../../../features/knowledge-sources/services/collections-api.service';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { KnowledgeRetrieverNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { SidePanelService } from '../../../services/side-panel.service';
import { InputMapComponent } from '../../input-map/input-map.component';
import { createInputMapFromPairs, getValidInputPairs, initializeInputMap } from '../node-panel-form.utils';

type RagKind = 'naive' | 'graph';

const NAIVE_DEFAULTS: NaiveRagSearchConfig = {
    search_limit: 3,
    similarity_threshold: 0.2,
};

const GRAPH_BASIC_DEFAULTS: GraphBasicSearchConfig = {
    prompt: null,
    k: 10,
    max_context_tokens: 12000,
};

const GRAPH_LOCAL_DEFAULTS: GraphLocalSearchConfig = {
    prompt: null,
    text_unit_prop: 0.5,
    community_prop: 0.15,
    conversation_history_max_turns: 5,
    top_k_entities: 10,
    top_k_relationships: 10,
    max_context_tokens: 12000,
};

// TODO review this component before any merge!
@Component({
    standalone: true,
    selector: 'app-knowledge-retriever-node-panel',
    imports: [
        CommonModule,
        ReactiveFormsModule,
        MatTooltipModule,
        CustomInputComponent,
        SelectComponent,
        SliderWithStepperComponent,
        InputNumberComponent,
        DualSliderComponent,
        RadioButtonComponent,
        TextareaComponent,
        InputMapComponent,
        CodeEditorComponent,
    ],
    templateUrl: './knowledge-retriever-node-panel.component.html',
    styleUrls: ['./knowledge-retriever-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class KnowledgeRetrieverNodePanelComponent extends BaseSidePanel<KnowledgeRetrieverNodeModel> {
    public override readonly isExpanded = input<boolean>(false);

    private readonly collectionsService = inject(CollectionsApiService);
    private readonly sidePanelService = inject(SidePanelService);

    // ── async data ──
    readonly collections = signal<GetCollectionRequest[]>([]);
    readonly loadingCollections = signal<boolean>(false);
    readonly rags = signal<GetCollectionRagsResponse[]>([]);
    readonly loadingRags = signal<boolean>(false);

    // ── UI state ──
    readonly searchConfigOpen = signal<boolean>(true);
    readonly isCodeEditorFullWidth = signal<boolean>(false);

    // The search-config sub-form is (re)built when rag_type changes — 'naive' and
    // 'graph' have completely different shapes. Held outside the main FormGroup
    // and swapped via a template @if.
    searchConfigsFormGroup: FormGroup | null = null;

    // Extracted controls so the DualSlider (which uses two 1-way bindings) can
    // read/write them without duplicating state.
    textUnitPropControl: FormControl | null = null;
    communityPropControl: FormControl | null = null;

    // "Instructions" (== `query`) is edited via CodeEditor in the expanded view.
    // Kept outside the form because CodeEditor is not a ControlValueAccessor here.
    queryText = '';

    private readonly codeChange$ = new Subject<void>();
    private readonly currentRagIdSignal = signal<number | null>(null);

    readonly searchMethodOptions: SelectItem[] = [
        { name: 'Basic', value: 'basic' },
        { name: 'Local', value: 'local' },
        // Global / DRIFT intentionally omitted — implemented in a different branch.
    ];

    readonly collectionItems = computed<SelectItem[]>(() => [
        { name: 'No collection', value: null },
        ...this.collections().map((c) => ({ name: c.collection_name, value: c.collection_id })),
    ]);

    readonly ragItems = computed<SelectItem[]>(() => this.rags().map((r) => ({ name: r.rag_type, value: r.rag_id })));

    /** Derives the rag kind ('naive' | 'graph') from the currently selected rag_id. */
    readonly selectedRagKind = computed<RagKind | null>(() => {
        const ragId = this.currentRagIdSignal();
        if (ragId == null) return null;
        const found = this.rags().find((r) => r.rag_id === ragId);
        const kind = found?.rag_type;
        return kind === 'naive' || kind === 'graph' ? kind : null;
    });

    constructor() {
        super();
        this.codeChange$
            .pipe(debounceTime(300), takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.sidePanelService.triggerAutosave());

        this.loadingCollections.set(true);
        this.collectionsService
            .getCollections()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (list) => {
                    this.collections.set(list);
                    this.loadingCollections.set(false);
                },
                error: () => this.loadingCollections.set(false),
            });
    }

    get activeColor(): string {
        return this.node().color || '#685fff';
    }

    get inputMapPairs(): FormArray {
        return this.form.get('input_map') as FormArray;
    }

    protected initializeForm(): FormGroup {
        const node = this.node();
        const data = node.data;

        this.queryText = data.query ?? '';
        this.currentRagIdSignal.set(data.rag_type);

        const form = this.fb.group({
            node_name: [node.node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [node.output_variable_path ?? ''],
            source_collection: [data.source_collection],
            rag_type: [data.rag_type],
            query: [data.query ?? ''],
        });

        initializeInputMap(form, node.input_map as Record<string, unknown> | null | undefined, this.fb);

        form.get('source_collection')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((collectionId: number | null) => this.onCollectionChange(collectionId));

        form.get('rag_type')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((ragId: number | null) => {
                this.currentRagIdSignal.set(ragId);
                this.rebuildSearchConfigsFormGroup(data.search_configs);
            });

        // Pre-load rags for the initially selected collection so the dropdown +
        // sub-form are populated on first render.
        if (data.source_collection != null) {
            this.loadRagsForCollection(data.source_collection);
        }

        this.rebuildSearchConfigsFormGroup(data.search_configs);

        return form;
    }

    protected createUpdatedNode(): KnowledgeRetrieverNodeModel {
        const node = this.node();
        const validPairs = getValidInputPairs(this.inputMapPairs);
        const inputMap = createInputMapFromPairs(validPairs);

        const ragId: number | null = this.form.value.rag_type ?? null;
        const kind = this.selectedRagKind();
        const searchConfigs = this.serializeSearchConfigs(kind);

        // Backend uses one column for `search_method`; keep top-level + nested mirror in sync.
        const graphMethod: GraphSearchMethod | null =
            kind === 'graph' && searchConfigs?.graph?.search_method ? searchConfigs.graph.search_method : null;

        return {
            ...node,
            node_name: this.form.value.node_name,
            input_map: inputMap,
            output_variable_path: this.form.value.output_variable_path || null,
            data: {
                ...node.data,
                source_collection: this.form.value.source_collection ?? null,
                rag_type: ragId,
                query: this.queryText,
                search_method: graphMethod,
                search_configs: searchConfigs,
            },
        };
    }

    // ── Instructions (query) ──

    onQueryCodeChange(code: string): void {
        this.queryText = code;
        this.form.patchValue({ query: code }, { emitEvent: false });
        this.codeChange$.next();
        this.notifyExternalChange();
    }

    toggleCodeEditorFullWidth(): void {
        this.isCodeEditorFullWidth.update((v) => !v);
    }

    toggleSearchConfig(): void {
        this.searchConfigOpen.update((v) => !v);
    }

    // ── DualSlider bridges (graph.local) ──

    onTextUnitPropUpdate(value: number): void {
        this.textUnitPropControl?.setValue(value);
    }

    onCommunityPropUpdate(value: number): void {
        this.communityPropControl?.setValue(value);
    }

    // ── Internals ──

    private onCollectionChange(collectionId: number | null): void {
        // Clear rag selection — rag_type must belong to source_collection per API.
        this.form.get('rag_type')!.setValue(null);
        if (collectionId == null) {
            this.rags.set([]);
            return;
        }
        this.loadRagsForCollection(collectionId);
    }

    private loadRagsForCollection(collectionId: number): void {
        this.loadingRags.set(true);
        this.collectionsService
            .getRagsByCollectionId(collectionId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (list) => {
                    this.rags.set(list);
                    this.loadingRags.set(false);
                    // Rebuild — the sub-form depends on rag kind which is derived from the rag list.
                    this.rebuildSearchConfigsFormGroup(this.node().data.search_configs);
                },
                error: () => this.loadingRags.set(false),
            });
    }

    private rebuildSearchConfigsFormGroup(existing: AgentSearchConfigs | null): void {
        const kind = this.selectedRagKind();
        if (kind === 'naive') {
            const cfg = existing?.naive ?? NAIVE_DEFAULTS;
            this.searchConfigsFormGroup = this.fb.group({
                search_limit: [cfg.search_limit ?? NAIVE_DEFAULTS.search_limit],
                similarity_threshold: [cfg.similarity_threshold ?? NAIVE_DEFAULTS.similarity_threshold],
            });
            this.textUnitPropControl = null;
            this.communityPropControl = null;
            return;
        }
        if (kind === 'graph') {
            const graph = existing?.graph;
            const basicCfg = graph?.basic ?? GRAPH_BASIC_DEFAULTS;
            const localCfg = graph?.local ?? GRAPH_LOCAL_DEFAULTS;
            const method: GraphSearchMethod = graph?.search_method ?? 'basic';

            this.textUnitPropControl = this.fb.control(localCfg.text_unit_prop ?? GRAPH_LOCAL_DEFAULTS.text_unit_prop);
            this.communityPropControl = this.fb.control(localCfg.community_prop ?? GRAPH_LOCAL_DEFAULTS.community_prop);

            this.searchConfigsFormGroup = this.fb.group({
                search_method: [method],
                basic: this.fb.group({
                    prompt: [basicCfg.prompt ?? null],
                    k: [basicCfg.k ?? GRAPH_BASIC_DEFAULTS.k],
                    max_context_tokens: [basicCfg.max_context_tokens ?? GRAPH_BASIC_DEFAULTS.max_context_tokens],
                }),
                local: this.fb.group({
                    prompt: [localCfg.prompt ?? null],
                    text_unit_prop: this.textUnitPropControl,
                    community_prop: this.communityPropControl,
                    conversation_history_max_turns: [
                        localCfg.conversation_history_max_turns ?? GRAPH_LOCAL_DEFAULTS.conversation_history_max_turns,
                    ],
                    max_context_tokens: [localCfg.max_context_tokens ?? GRAPH_LOCAL_DEFAULTS.max_context_tokens],
                    top_k_entities: [localCfg.top_k_entities ?? GRAPH_LOCAL_DEFAULTS.top_k_entities],
                    top_k_relationships: [localCfg.top_k_relationships ?? GRAPH_LOCAL_DEFAULTS.top_k_relationships],
                }),
            });
            return;
        }
        this.searchConfigsFormGroup = null;
        this.textUnitPropControl = null;
        this.communityPropControl = null;
    }

    /** Reads the current sub-form back into the API-shaped `search_configs`. */
    private serializeSearchConfigs(kind: RagKind | null): AgentSearchConfigs | null {
        if (!kind || !this.searchConfigsFormGroup) return null;
        const value = this.searchConfigsFormGroup.value;
        if (kind === 'naive') {
            return {
                naive: {
                    search_limit: Number(value.search_limit) || NAIVE_DEFAULTS.search_limit,
                    similarity_threshold: Number(value.similarity_threshold) || NAIVE_DEFAULTS.similarity_threshold,
                },
            };
        }
        // kind === 'graph'
        const method: GraphSearchMethod = value.search_method ?? 'basic';
        return {
            graph: {
                search_method: method,
                basic: {
                    prompt: value.basic?.prompt ?? null,
                    k: Number(value.basic?.k) || GRAPH_BASIC_DEFAULTS.k,
                    max_context_tokens:
                        Number(value.basic?.max_context_tokens) || GRAPH_BASIC_DEFAULTS.max_context_tokens,
                },
                local: {
                    prompt: value.local?.prompt ?? null,
                    text_unit_prop: Number(value.local?.text_unit_prop) || GRAPH_LOCAL_DEFAULTS.text_unit_prop,
                    community_prop: Number(value.local?.community_prop) || GRAPH_LOCAL_DEFAULTS.community_prop,
                    conversation_history_max_turns:
                        Number(value.local?.conversation_history_max_turns) ||
                        GRAPH_LOCAL_DEFAULTS.conversation_history_max_turns,
                    max_context_tokens:
                        Number(value.local?.max_context_tokens) || GRAPH_LOCAL_DEFAULTS.max_context_tokens,
                    top_k_entities: Number(value.local?.top_k_entities) || GRAPH_LOCAL_DEFAULTS.top_k_entities,
                    top_k_relationships:
                        Number(value.local?.top_k_relationships) || GRAPH_LOCAL_DEFAULTS.top_k_relationships,
                },
            },
        };
    }
}
