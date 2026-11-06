import { ChangeDetectionStrategy, Component, computed, inject, input, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    AppSvgIconComponent,
    ColumnResizeDividerComponent,
    CopyButtonComponent,
    createColumnWidthState,
    CustomInputComponent,
    RagTabComponent,
    SelectComponent,
    SelectItem,
    TemplateTextareaComponent,
    TooltipComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { AgentSearchConfigs, GraphSearchMethod } from '@shared/models';
import { RAG_SUGGEST_API } from '@shared/services';
import { Subject } from 'rxjs';
import { debounceTime } from 'rxjs/operators';

import {
    GetCollectionRagsResponse,
    GetCollectionRequest,
} from '../../../../features/knowledge-sources/models/collection.model';
import { CollectionsApiService } from '../../../../features/knowledge-sources/services/collections-api.service';
import { AgentsService } from '../../../../features/staff/services/staff.service';
import { IfFlowEditableDirective } from '../../../core/directives/if-flow-editable.directive';
import { KnowledgeRetrieverNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { NODE_PANEL_DIFF } from '../../../core/providers/node-panel-diff.token';
import { SidePanelService } from '../../../services/side-panel.service';
import { fieldGroupChange, linkedEntityFormat, mapFieldRowChanges } from '../../../utils/diff';
import { DiffFieldMarkChange, DiffFieldMarkComponent } from '../../diff-field-mark/diff-field-mark.component';
import { InputMapComponent } from '../../input-map/input-map.component';
import { createInputMapFromPairs, getValidInputPairs, initializeInputMap } from '../node-panel-form.utils';
import { InputsYouCanUseComponent } from '../shared/inputs-you-can-use/inputs-you-can-use.component';
import { buildGraphSearchConfig } from './knowledge-retriever-search-configs.util';

type RagKind = 'naive' | 'graph';

interface RagChoice {
    rag_id: number;
    rag_type: RagKind;
}

@Component({
    selector: 'app-knowledge-retriever-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        SelectComponent,
        InputMapComponent,
        TemplateTextareaComponent,
        TooltipComponent,
        AppSvgIconComponent,
        CopyButtonComponent,
        ColumnResizeDividerComponent,
        RagTabComponent,
        InputsYouCanUseComponent,
        ValidationErrorsComponent,
        IfFlowEditableDirective,
        DiffFieldMarkComponent,
    ],
    templateUrl: './knowledge-retriever-node-panel.component.html',
    styleUrls: ['./knowledge-retriever-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [{ provide: RAG_SUGGEST_API, useExisting: AgentsService }],
})
export class KnowledgeRetrieverNodePanelComponent extends BaseSidePanel<KnowledgeRetrieverNodeModel> {
    public override readonly isExpanded = input<boolean>(false);

    private readonly collectionsService = inject(CollectionsApiService);
    private readonly sidePanelService = inject(SidePanelService);
    private readonly panelDiff = inject(NODE_PANEL_DIFF);

    readonly collections = signal<GetCollectionRequest[]>([]);
    readonly loadingCollections = signal<boolean>(false);
    readonly rags = signal<GetCollectionRagsResponse[]>([]);
    readonly loadingRags = signal<boolean>(false);

    readonly searchConfigOpen = signal<boolean>(true);
    readonly isFormCollapsed = signal<boolean>(false);
    protected readonly leftColumnWidth = createColumnWidthState('knowledge-retriever-node', 406);
    readonly availableInputs = signal<string[]>([]);

    private readonly queryTextareaCollapsed = viewChild<TemplateTextareaComponent>('queryTextareaCollapsed');
    private readonly queryTextareaExpanded = viewChild<TemplateTextareaComponent>('queryTextareaExpanded');

    private readonly codeChange$ = new Subject<void>();
    private readonly currentRagChoice = signal<RagChoice | null>(null);

    private readonly formSignal = signal<FormGroup | null>(null);
    readonly ragTabFormList = computed<FormGroup[]>(() => {
        const f = this.formSignal();
        return f ? [f] : [];
    });
    readonly ragTabSearchConfigs = computed<AgentSearchConfigs | null>(() => this.node().data.search_configs ?? null);

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

    /** Changes tab of a version preview: what a restore does to each Input List row; `null` anywhere else. */
    protected readonly inputMapRowChanges = computed(() => mapFieldRowChanges(this.panelDiff(), 'input_map'));
    /** The RAG picked is one field holding two diffed values, its type and its id. */
    protected readonly ragChange = computed<DiffFieldMarkChange | null>(() => {
        const data = this.node().data;
        return fieldGroupChange(this.panelDiff(), { rag_type: data.rag_type, rag_id: data.rag_id });
    });
    /** The search settings are one section holding two diffed values, the settings and the search method. */
    protected readonly searchSettingsChange = computed<DiffFieldMarkChange | null>(() => {
        const data = this.node().data;
        return fieldGroupChange(this.panelDiff(), {
            search_method: data.search_method,
            search_configs: data.search_configs,
        });
    });
    /** The loaded collections name a changed collection in the mark's tooltip; one not loaded: `collection #id`. */
    protected readonly collectionNameFormat = linkedEntityFormat(
        'collection',
        (id) => this.collections().find((collection) => collection.collection_id === id)?.collection_name
    );
    /**
     * A RAG has no name: the select shows its type. One the select does not list (another collection's, or one
     * that is gone) also gets its id, so two RAGs of one type still read apart.
     */
    protected readonly ragFormat = (value: unknown): string => {
        const { rag_type: type, rag_id: id } = value as { rag_type: unknown; rag_id: unknown };
        if (id == null || this.rags().some((rag) => rag.rag_id === id && rag.rag_type === type)) return String(type);
        return type == null ? `RAG #${String(id)}` : `${String(type)} (RAG #${String(id)})`;
    };

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
        return 'var(--accent-color)';
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
            knowledge_collection: [data.source_collection],
            rag: this.fb.control<RagChoice | null>(null),
            query: [data.query ?? '', Validators.required],
        });

        initializeInputMap(form, node.input_map as Record<string, unknown> | null | undefined, this.fb);

        const inputMap = form.get('input_map') as FormArray;
        this.updateAvailableInputs(inputMap);
        inputMap.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.updateAvailableInputs(inputMap));

        form.get('knowledge_collection')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((collectionId: number | null) => this.onCollectionChange(collectionId));

        form.get('rag')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((choice: RagChoice | null) => this.currentRagChoice.set(choice));

        form.get('query')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.codeChange$.next());

        if (data.source_collection != null) {
            this.loadRagsForCollection(data.source_collection);
        }

        this.formSignal.set(form);
        return form;
    }

    protected createUpdatedNode(): KnowledgeRetrieverNodeModel {
        const node = this.node();
        const validPairs = getValidInputPairs(this.inputMapPairs);
        const inputMap = createInputMapFromPairs(validPairs);

        const choice: RagChoice | null = this.form.value.rag ?? null;
        const kind = this.selectedRagKind();
        const rawConfigs = this.form.get('search_configs')?.value;

        let searchConfigs: AgentSearchConfigs | null = null;
        let graphMethod: GraphSearchMethod | null = null;
        if (kind === 'naive' && rawConfigs) {
            searchConfigs = { naive: rawConfigs };
        } else if (kind === 'graph' && rawConfigs) {
            searchConfigs = { graph: buildGraphSearchConfig(rawConfigs, node.data.search_configs?.graph) };
            graphMethod = rawConfigs.search_method ?? null;
        }

        return {
            ...node,
            node_name: this.form.value.node_name,
            input_map: inputMap,
            output_variable_path: this.form.value.output_variable_path || null,
            data: {
                ...node.data,
                source_collection: this.form.value.knowledge_collection ?? null,
                rag_type: kind,
                rag_id: choice?.rag_id ?? null,
                query: this.form.value.query ?? '',
                search_method: graphMethod,
                search_configs: searchConfigs,
            },
        };
    }

    toggleSearchConfig(): void {
        this.searchConfigOpen.update((v) => !v);
    }

    insertInputToQuery(name: string): void {
        const target = this.queryTextareaCollapsed() ?? this.queryTextareaExpanded();
        target?.insertVariable(name);
    }

    private updateAvailableInputs(pairs: FormArray): void {
        const keys = pairs.controls.map((c) => ((c.value?.key as string) ?? '').trim()).filter((k) => k !== '');
        this.availableInputs.set(Array.from(new Set(keys)));
    }

    private onCollectionChange(collectionId: number | null): void {
        this.form.get('rag')!.setValue(null);
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
                },
                error: () => this.loadingRags.set(false),
            });
    }

    private rehydrateRagChoiceFromSavedData(): void {
        if (this.form.get('rag')!.value != null) return;

        const savedKind = this.node().data.rag_type;
        if (savedKind == null) return;

        const savedId = this.node().data.rag_id;
        const match =
            this.rags().find((r) => r.rag_type === savedKind && r.rag_id === savedId) ??
            this.rags().find((r) => r.rag_type === savedKind);
        if (!match) return;

        this.form.get('rag')!.setValue({ rag_id: match.rag_id, rag_type: savedKind });
    }
}
