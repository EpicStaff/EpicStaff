import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    CopyButtonComponent,
    CustomInputComponent,
    DualSliderComponent,
    InputNumberComponent,
    RadioButtonComponent,
    SelectComponent,
    SelectItem,
    SliderWithStepperComponent,
    TemplateTextareaComponent,
    TextareaComponent,
    TooltipComponent,
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
import { KnowledgeRetrieverNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { SidePanelService } from '../../../services/side-panel.service';
import { InputMapComponent } from '../../input-map/input-map.component';
import { createInputMapFromPairs, getValidInputPairs, initializeInputMap } from '../node-panel-form.utils';

type RagKind = 'naive' | 'graph';

interface RagChoice {
    rag_id: number;
    rag_type: RagKind;
}

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

@Component({
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
        TemplateTextareaComponent,
        InputMapComponent,
        TextareaComponent,
        TooltipComponent,
        AppSvgIconComponent,
        CopyButtonComponent,
    ],
    templateUrl: './knowledge-retriever-node-panel.component.html',
    styleUrls: ['./knowledge-retriever-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class KnowledgeRetrieverNodePanelComponent extends BaseSidePanel<KnowledgeRetrieverNodeModel> {
    public override readonly isExpanded = input<boolean>(false);

    private readonly collectionsService = inject(CollectionsApiService);
    private readonly sidePanelService = inject(SidePanelService);

    readonly collections = signal<GetCollectionRequest[]>([]);
    readonly loadingCollections = signal<boolean>(false);
    readonly rags = signal<GetCollectionRagsResponse[]>([]);
    readonly loadingRags = signal<boolean>(false);

    readonly searchConfigOpen = signal<boolean>(true);
    readonly isCodeEditorFullWidth = signal<boolean>(false);

    searchConfigsFormGroup: FormGroup | null = null;

    textUnitPropControl: FormControl | null = null;
    communityPropControl: FormControl | null = null;

    private readonly codeChange$ = new Subject<void>();
    private readonly currentRagChoice = signal<RagChoice | null>(null);

    // TODO add global and drift methods when they are ready, then
    // TODO investigate if we can reuse same logic in both: here, and agent create/update modal
    readonly searchMethodOptions: SelectItem[] = [
        { name: 'Basic', value: 'basic' },
        { name: 'Local', value: 'local' },
    ];

    readonly collectionItems = computed<SelectItem[]>(() => [
        { name: 'No collection', value: null },
        ...this.collections().map((c) => ({ name: c.collection_name, value: c.collection_id })),
    ]);

    readonly ragItems = computed<SelectItem<RagChoice>[]>(() =>
        this.rags()
            .filter((r) => r.rag_type === 'naive' || r.rag_type === 'graph')
            .map((r) => ({
                name: r.rag_type,
                value: { rag_id: r.rag_id, rag_type: r.rag_type as RagKind },
            }))
    );

    readonly selectedRagKind = computed<RagKind | null>(() => this.currentRagChoice()?.rag_type ?? null);

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

        this.currentRagChoice.set(null);

        const form = this.fb.group({
            node_name: [node.node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [node.output_variable_path ?? ''],
            source_collection: [data.source_collection],
            rag_type: this.fb.control<RagChoice | null>(null),
            query: [data.query ?? ''],
        });

        initializeInputMap(form, node.input_map as Record<string, unknown> | null | undefined, this.fb);

        form.get('source_collection')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((collectionId: number | null) => this.onCollectionChange(collectionId));

        form.get('rag_type')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((choice: RagChoice | null) => {
                this.currentRagChoice.set(choice);
                this.rebuildSearchConfigsFormGroup(data.search_configs);
            });

        form.get('query')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.codeChange$.next());

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

        const choice: RagChoice | null = this.form.value.rag_type ?? null;
        const kind = this.selectedRagKind();
        const searchConfigs = this.serializeSearchConfigs(kind);

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
                rag_type: choice?.rag_id ?? null,
                query: this.form.value.query ?? '',
                search_method: graphMethod,
                search_configs: searchConfigs,
            },
        };
    }

    toggleCodeEditorFullWidth(): void {
        this.isCodeEditorFullWidth.update((v) => !v);
    }

    toggleSearchConfig(): void {
        this.searchConfigOpen.update((v) => !v);
    }

    onTextUnitPropUpdate(value: number): void {
        this.textUnitPropControl?.setValue(value);
    }

    onCommunityPropUpdate(value: number): void {
        this.communityPropControl?.setValue(value);
    }

    private onCollectionChange(collectionId: number | null): void {
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
                    this.rehydrateRagChoiceFromSavedData();
                    this.rebuildSearchConfigsFormGroup(this.node().data.search_configs);
                },
                error: () => this.loadingRags.set(false),
            });
    }

    private rehydrateRagChoiceFromSavedData(): void {
        if (this.form.get('rag_type')!.value != null) return;

        const savedRagId = this.node().data.rag_type;
        if (savedRagId == null) return;

        const match = this.rags().find(
            (r) => r.rag_id === savedRagId && (r.rag_type === 'naive' || r.rag_type === 'graph')
        );
        if (!match) return;

        this.form.get('rag_type')!.setValue({ rag_id: match.rag_id, rag_type: match.rag_type as RagKind });
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
