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
import { FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { SelectComponent, SelectItem, TabButtonComponent } from '@shared/components';
import { TooltipOnOverflowDirective } from '@shared/directives';
import { AgentSearchConfigs, GraphSearchMethod, NaiveRagSearchConfig } from '@shared/models';
import { Subscription } from 'rxjs';
import { debounceTime } from 'rxjs/operators';

import { RagTabComponent } from '../../../../../../../../../shared/components/create-agent-form-dialog/tabs/rag/rag-tab.component';
import { CollectionsApiService } from '../../../../../../../../knowledge-sources/services/collections-api.service';
import { SurfaceKnowledge } from '../../../../../../../models/surface.model';
import { SurfaceCollectionOption } from '../../../../../../../models/surface-card.model';

type RagKind = 'naive' | 'graph' | null;

@Component({
    selector: 'app-surface-knowledge-advanced',
    imports: [
        ReactiveFormsModule,
        SelectComponent,
        TabButtonComponent,
        MatTooltipModule,
        TooltipOnOverflowDirective,
        RagTabComponent,
    ],
    templateUrl: './surface-knowledge-advanced.component.html',
    styleUrls: ['./surface-knowledge-advanced.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SurfaceKnowledgeAdvancedComponent implements OnDestroy {
    private readonly fb = inject(FormBuilder);
    private readonly destroyRef = inject(DestroyRef);
    private readonly collectionsApi = inject(CollectionsApiService);

    collections = input.required<SurfaceCollectionOption[]>();
    knowledge = input.required<SurfaceKnowledge[]>();
    readOnly = input<boolean>(false);
    /** The owning AgentDefinition's llm_config — forwarded to the embedded RAG tab
     * so suggested-params requests know which LLM's context window to use. */
    llmConfigId = input<number | null>(null);

    readonly knowledgeChange = output<SurfaceKnowledge>();

    readonly activeCollectionId = signal<number | null>(null);

    /** The RAG-kind picker's own small form (just `{ rag: RagKind }`) — kept
     * separate from the rag-tab adapter form below so this component still owns
     * the per-collection kind picker exactly as before. */
    readonly form = signal<FormGroup | null>(null);
    /** Adapter form fed to the embedded `<app-rag-tab>`: `{ knowledge_collection, rag }`,
     * matching the shape `RagTabComponent` expects. It sets its own `search_configs`
     * control onto this group once initialized. */
    readonly ragTabForm = signal<FormGroup | null>(null);
    // `RagTabComponent.ngOnInit()` wires itself up once against whatever `form`
    // it's first given — swapping the `[form]` input to a different FormGroup
    // instance later does NOT re-run ngOnInit, so simply rebinding wouldn't pick
    // up the new collection's controls. Wrapping in a single-item @for keyed by
    // this list's own FormGroup reference forces Angular to destroy/recreate the
    // <app-rag-tab> element (and re-run its ngOnInit) every time rebuildForm()
    // produces a new instance, i.e. on every collection switch.
    readonly ragTabFormList = computed<FormGroup[]>(() => {
        const f = this.ragTabForm();
        return f ? [f] : [];
    });
    readonly ragTabSearchConfigs = signal<AgentSearchConfigs | null>(null);
    readonly currentGraphMethod = signal<GraphSearchMethod | null>(null);

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

    /** Methods that don't yet have backend storage for this (Surface) agent type —
     * the embedded rag-tab renders full UI for them anyway, but a save silently
     * drops the data server-side until the corresponding model/serializer exists. */
    readonly currentMethodNotPersisted = computed<boolean>(() => {
        const method = this.currentGraphMethod();
        return method === 'global' || method === 'drift';
    });

    private formSub = new Subscription();
    private lastEmitted: string | null = null;
    // Tracks the form a debounced emitCurrent() is currently pending for, so a
    // collection switch or destroy mid-debounce can flush it instead of the
    // unsubscribe below silently dropping the edit.
    private pendingCollectionId: number | null = null;
    private pendingRagTabForm: FormGroup | null = null;

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
        if (
            item?.graph_basic_search_config ||
            item?.graph_local_search_config ||
            item?.graph_global_search_config ||
            item?.graph_drift_search_config
        ) {
            return 'graph';
        }
        return null;
    }

    private storedGraphMethod(item: SurfaceKnowledge | undefined): GraphSearchMethod {
        if (item?.graph_local_search_config) return 'local';
        if (item?.graph_global_search_config) return 'global';
        if (item?.graph_drift_search_config) return 'drift';
        return 'basic';
    }

    selectCollection(id: number): void {
        this.activeCollectionId.set(id);
    }

    ngOnDestroy(): void {
        this.flushPending();
        this.formSub.unsubscribe();
    }

    /** Emits synchronously whatever emitCurrent() had debounced for the collection
     * being left, instead of letting the unsubscribe below cancel it silently. */
    private flushPending(): void {
        if (this.pendingCollectionId != null && this.pendingRagTabForm) {
            this.emitCurrent(this.pendingCollectionId, this.pendingRagTabForm);
        }
    }

    private rebuildForm(collectionId: number | null): void {
        this.flushPending();
        this.formSub.unsubscribe();
        this.formSub = new Subscription();
        this.lastEmitted = null;

        if (collectionId == null) {
            this.pendingCollectionId = null;
            this.pendingRagTabForm = null;
            this.form.set(null);
            this.ragTabForm.set(null);
            this.ragTabSearchConfigs.set(null);
            this.currentGraphMethod.set(null);
            return;
        }

        const item = this.knowledge().find((k) => k.collection === collectionId);
        const kind = this.storedRagKind(collectionId);

        const fg = this.fb.group({ rag: [kind] });
        if (this.readOnly()) fg.disable({ emitEvent: false });
        this.form.set(fg);

        const ragTabForm = this.fb.group({
            knowledge_collection: [collectionId],
            // RagTabComponent.ngOnInit() treats a truthy `rag` value as "a kind is
            // selected" — must be plain `null`, not `{ rag_id: null, rag_type: null }`,
            // when nothing's picked yet, or it'll try to init an empty search-config form.
            rag: [kind ? { rag_id: null, rag_type: kind } : null],
        });
        this.ragTabForm.set(ragTabForm);
        this.ragTabSearchConfigs.set(this.buildSearchConfigsInput(item));
        this.currentGraphMethod.set(kind === 'graph' ? this.storedGraphMethod(item) : null);
        this.pendingCollectionId = collectionId;
        this.pendingRagTabForm = ragTabForm;

        // The visible RAG-kind select (`fg.rag`) drives the adapter form's `rag`
        // control that `<app-rag-tab>` actually reads from.
        this.formSub.add(
            fg.get('rag')!.valueChanges.subscribe((newKind: RagKind) => {
                ragTabForm.get('rag')!.setValue(newKind ? { rag_id: null, rag_type: newKind } : null);
            })
        );

        this.formSub.add(
            ragTabForm.valueChanges.subscribe(() => {
                const method = ragTabForm.get('search_configs')?.get('search_method')?.value ?? null;
                this.currentGraphMethod.set(method);
            })
        );

        this.formSub.add(
            ragTabForm.valueChanges.pipe(debounceTime(500)).subscribe(() => this.emitCurrent(collectionId, ragTabForm))
        );
    }

    private buildSearchConfigsInput(item: SurfaceKnowledge | undefined): AgentSearchConfigs | null {
        if (!item) return null;
        const naive: NaiveRagSearchConfig | undefined = item.naive_search_config
            ? {
                  search_limit: item.naive_search_config.search_limit,
                  similarity_threshold: Number(item.naive_search_config.similarity_threshold),
              }
            : undefined;
        return {
            naive,
            graph: {
                search_method: this.storedGraphMethod(item),
                basic: item.graph_basic_search_config
                    ? { ...item.graph_basic_search_config, prompt: item.graph_basic_search_config.prompt ?? null }
                    : undefined,
                local: item.graph_local_search_config
                    ? { ...item.graph_local_search_config, prompt: item.graph_local_search_config.prompt ?? null }
                    : undefined,
                global: item.graph_global_search_config ?? undefined,
                drift: item.graph_drift_search_config ?? undefined,
            },
        };
    }

    private emitCurrent(collectionId: number, ragTabForm: FormGroup): void {
        if (this.readOnly()) return;

        const searchConfigsCtrl = ragTabForm.get('search_configs');
        if (!searchConfigsCtrl) return; // rag-tab hasn't initialized yet (no rag kind picked)

        const ragValue = ragTabForm.get('rag')?.value as { rag_type: RagKind } | null;
        const ragType = ragValue?.rag_type ?? null;
        const raw = searchConfigsCtrl.getRawValue();

        let item: SurfaceKnowledge | null = null;

        if (ragType === 'naive') {
            item = {
                collection: collectionId,
                naive_search_config: {
                    search_limit: raw.search_limit,
                    similarity_threshold: Number(Number(raw.similarity_threshold).toFixed(2)),
                },
                graph_basic_search_config: null,
                graph_local_search_config: null,
                graph_global_search_config: null,
                graph_drift_search_config: null,
            };
        } else if (ragType === 'graph') {
            const method = raw.search_method as GraphSearchMethod;
            item = {
                collection: collectionId,
                naive_search_config: null,
                graph_basic_search_config:
                    method === 'basic' ? { ...raw.basic, prompt: raw.basic.prompt || null } : null,
                graph_local_search_config:
                    method === 'local' ? { ...raw.local, prompt: raw.local.prompt || null } : null,
                // Sent even though the backend doesn't persist these yet for Surfaces
                // (silently dropped, not rejected — see surface.model.ts) so nothing
                // further needs to change here once that support lands.
                graph_global_search_config:
                    method === 'global'
                        ? {
                              ...raw.global,
                              map_prompt: raw.global.map_prompt || null,
                              reduce_prompt: raw.global.reduce_prompt || null,
                              knowledge_prompt: raw.global.knowledge_prompt || null,
                          }
                        : null,
                graph_drift_search_config:
                    method === 'drift'
                        ? {
                              ...raw.drift,
                              prompt: raw.drift.prompt || null,
                              reduce_prompt: raw.drift.reduce_prompt || null,
                          }
                        : null,
            };
        }

        if (!item || searchConfigsCtrl.invalid) return;
        const json = JSON.stringify(item);
        if (json === this.lastEmitted) return;
        this.lastEmitted = json;
        this.knowledgeChange.emit(item);
    }
}
