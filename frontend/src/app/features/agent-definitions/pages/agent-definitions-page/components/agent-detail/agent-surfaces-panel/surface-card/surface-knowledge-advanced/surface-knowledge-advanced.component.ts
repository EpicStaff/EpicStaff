import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    input,
    OnDestroy,
    output,
    signal,
    untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    InputNumberComponent,
    RadioButtonComponent,
    SelectComponent,
    SelectItem,
    SliderWithStepperComponent,
    TabButtonComponent,
    TextareaComponent,
} from '@shared/components';
import { DEFAULT_STEP_SIZE } from '@shared/constants';
import { TooltipOnOverflowDirective } from '@shared/directives';
import { Subscription } from 'rxjs';
import { debounceTime } from 'rxjs/operators';

import { CollectionsApiService } from '../../../../../../../../knowledge-sources/services/collections-api.service';
import { SurfaceKnowledge } from '../../../../../../../models/surface.model';
import { SurfaceCollectionOption } from '../../../../../../../models/surface-card.model';

type RagKind = 'naive' | 'graph' | null;

@Component({
    selector: 'app-surface-knowledge-advanced',
    imports: [
        ReactiveFormsModule,
        SelectComponent,
        RadioButtonComponent,
        TextareaComponent,
        InputNumberComponent,
        SliderWithStepperComponent,
        TabButtonComponent,
        MatTooltipModule,
        TooltipOnOverflowDirective,
    ],
    templateUrl: './surface-knowledge-advanced.component.html',
    styleUrls: ['./surface-knowledge-advanced.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SurfaceKnowledgeAdvancedComponent implements OnDestroy {
    protected readonly DEFAULT_STEP_SIZE = DEFAULT_STEP_SIZE;

    private readonly fb = inject(FormBuilder);
    private readonly destroyRef = inject(DestroyRef);
    private readonly collectionsApi = inject(CollectionsApiService);

    collections = input.required<SurfaceCollectionOption[]>();
    knowledge = input.required<SurfaceKnowledge[]>();
    readOnly = input<boolean>(false);

    readonly knowledgeChange = output<SurfaceKnowledge>();

    readonly activeCollectionId = signal<number | null>(null);
    readonly form = signal<FormGroup | null>(null);

    private readonly ragKindItems: SelectItem[] = [
        { name: 'Naive RAG', value: 'naive' },
        { name: 'Graph RAG', value: 'graph' },
    ];

    private readonly availableRagsByCollection = signal<ReadonlyMap<number, string[]>>(new Map());
    private readonly ragsLoadingIds = signal<ReadonlySet<number>>(new Set());
    private readonly requestedRagIds = new Set<number>();

    /** Only RAG kinds actually built for the active collection (plus the stored kind, so saved configs stay visible). */
    readonly ragItems = computed<SelectItem[]>(() => {
        const id = this.activeCollectionId();
        if (id == null) return [];
        const kinds = new Set<string>(this.availableRagsByCollection().get(id) ?? []);
        const stored = this.storedRagKind(id);
        if (stored) kinds.add(stored);
        return this.ragKindItems.filter((i) => kinds.has(i.value as string));
    });

    readonly ragsLoading = computed<boolean>(() => {
        const id = this.activeCollectionId();
        return id != null && this.ragsLoadingIds().has(id);
    });

    readonly noRagsAvailable = computed<boolean>(() => !this.ragsLoading() && this.ragItems().length === 0);

    readonly searchTypes: SelectItem[] = [
        { name: 'Basic', value: 'basic' },
        { name: 'Local', value: 'local' },
        { name: 'Global', value: 'global' },
        { name: 'DRIFT', value: 'drift' },
    ];

    private formSub?: Subscription;
    private lastEmitted: string | null = null;

    constructor() {
        effect(() => {
            const cols = this.collections();
            const active = this.activeCollectionId();
            if (active != null && cols.some((c) => c.id === active)) return;
            this.activeCollectionId.set(cols[0]?.id ?? null);
        });

        effect(() => {
            const id = this.activeCollectionId();
            untracked(() => this.rebuildForm(id));
        });

        effect(() => {
            const id = this.activeCollectionId();
            if (id == null || this.requestedRagIds.has(id)) return;
            this.requestedRagIds.add(id);
            untracked(() => this.loadAvailableRags(id));
        });
    }

    private loadAvailableRags(collectionId: number): void {
        this.ragsLoadingIds.update((s) => new Set(s).add(collectionId));
        this.collectionsApi
            .getRagsByCollectionId(collectionId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (rags) => {
                    const types = [...new Set(rags.map((r) => r.rag_type))];
                    this.availableRagsByCollection.update((m) => new Map(m).set(collectionId, types));
                    this.clearRagsLoading(collectionId);
                },
                error: () => {
                    this.requestedRagIds.delete(collectionId);
                    this.clearRagsLoading(collectionId);
                },
            });
    }

    private clearRagsLoading(collectionId: number): void {
        this.ragsLoadingIds.update((s) => {
            const next = new Set(s);
            next.delete(collectionId);
            return next;
        });
    }

    private storedRagKind(collectionId: number): RagKind {
        const item = this.knowledge().find((k) => k.collection === collectionId);
        if (item?.naive_search_config) return 'naive';
        if (item?.graph_basic_search_config || item?.graph_local_search_config) return 'graph';
        return null;
    }

    selectCollection(id: number): void {
        this.activeCollectionId.set(id);
    }

    ngOnDestroy(): void {
        this.formSub?.unsubscribe();
    }

    private rebuildForm(collectionId: number | null): void {
        this.formSub?.unsubscribe();
        this.lastEmitted = null;
        if (collectionId == null) {
            this.form.set(null);
            return;
        }

        const item = this.knowledge().find((k) => k.collection === collectionId);
        const fg = this.buildForm(item);
        if (this.readOnly()) fg.disable({ emitEvent: false });
        this.form.set(fg);
        this.formSub = fg.valueChanges.pipe(debounceTime(500)).subscribe(() => this.emitCurrent(collectionId, fg));
    }

    private buildForm(item: SurfaceKnowledge | undefined): FormGroup {
        const rag: RagKind = item?.naive_search_config
            ? 'naive'
            : item?.graph_basic_search_config || item?.graph_local_search_config
              ? 'graph'
              : null;
        const method = item?.graph_local_search_config ? 'local' : 'basic';
        const naive = item?.naive_search_config;
        const basic = item?.graph_basic_search_config;
        const local = item?.graph_local_search_config;

        return this.fb.group({
            rag: [rag],
            search_method: [method, [Validators.required]],
            naive: this.fb.group({
                search_limit: [naive?.search_limit ?? 3, [Validators.min(1), Validators.max(1000)]],
                similarity_threshold: [
                    Number(naive?.similarity_threshold ?? 0.2),
                    [Validators.min(0), Validators.max(1)],
                ],
            }),
            basic: this.fb.group({
                prompt: [basic?.prompt ?? null, [Validators.maxLength(1000)]],
                k: [basic?.k ?? 10, [Validators.required, Validators.min(1), Validators.max(100)]],
                max_context_tokens: [
                    basic?.max_context_tokens ?? 12000,
                    [Validators.required, Validators.min(100), Validators.max(100000)],
                ],
            }),
            local: this.fb.group({
                prompt: [local?.prompt ?? null, [Validators.maxLength(1000)]],
                text_unit_prop: [local?.text_unit_prop ?? 0.5, [Validators.min(0), Validators.max(1)]],
                community_prop: [local?.community_prop ?? 0.15, [Validators.min(0), Validators.max(1)]],
                conversation_history_max_turns: [
                    local?.conversation_history_max_turns ?? 5,
                    [Validators.required, Validators.min(1), Validators.max(50)],
                ],
                top_k_entities: [
                    local?.top_k_entities ?? 10,
                    [Validators.required, Validators.min(1), Validators.max(100)],
                ],
                top_k_relationships: [
                    local?.top_k_relationships ?? 10,
                    [Validators.required, Validators.min(1), Validators.max(100)],
                ],
                max_context_tokens: [
                    local?.max_context_tokens ?? 12000,
                    [Validators.required, Validators.min(100), Validators.max(100000)],
                ],
            }),
        });
    }

    private emitCurrent(collectionId: number, fg: FormGroup): void {
        if (this.readOnly()) return;

        const v = fg.getRawValue();
        let item: SurfaceKnowledge | null = null;

        if (v.rag === 'naive') {
            item = {
                collection: collectionId,
                naive_search_config: {
                    search_limit: v.naive.search_limit,
                    similarity_threshold: Number(Number(v.naive.similarity_threshold).toFixed(2)),
                },
                graph_basic_search_config: null,
                graph_local_search_config: null,
            };
        } else if (v.rag === 'graph' && v.search_method === 'basic') {
            item = {
                collection: collectionId,
                naive_search_config: null,
                graph_basic_search_config: {
                    prompt: v.basic.prompt || null,
                    k: v.basic.k,
                    max_context_tokens: v.basic.max_context_tokens,
                },
                graph_local_search_config: null,
            };
        } else if (v.rag === 'graph' && v.search_method === 'local') {
            item = {
                collection: collectionId,
                naive_search_config: null,
                graph_basic_search_config: null,
                graph_local_search_config: {
                    prompt: v.local.prompt || null,
                    text_unit_prop: v.local.text_unit_prop,
                    community_prop: v.local.community_prop,
                    conversation_history_max_turns: v.local.conversation_history_max_turns,
                    top_k_entities: v.local.top_k_entities,
                    top_k_relationships: v.local.top_k_relationships,
                    max_context_tokens: v.local.max_context_tokens,
                },
            };
        }

        if (!item || fg.invalid) return;
        const json = JSON.stringify(item);
        if (json === this.lastEmitted) return;
        this.lastEmitted = json;
        this.knowledgeChange.emit(item);
    }
}
