import { computed, inject, Injectable, Signal, signal, WritableSignal } from '@angular/core';
import { Observable, of } from 'rxjs';
import { map, switchMap, tap } from 'rxjs/operators';

import { ToastService } from '../../../../../../services/notifications';
import { CollectionGraphRag, CreateGraphRagIndexConfigRequest } from '../../../../models/graph-rag.model';
import { CollectionsStorageService } from '../../../../services/collections-storage.service';
import { GraphRagService } from '../../../../services/graph-rag.service';
import { GraphRagDocumentsStorageService } from '../../../../services/graph-rag-documents-storage.service';
import { KnowledgeSourcesPollingService } from '../../../../services/knowledge-sources-polling.service';
import { RagIndexingService } from '../../../../services/rag-indexing.service';
import { GraphRagConfigurationComponent } from '../../../graph-rag-configuration/graph-rag-configuration.component';
import { RagCreationStrategy } from '../interfaces/rag-creation-strategy.interface';

@Injectable({
    providedIn: 'root',
})
export class GraphRagStrategy implements RagCreationStrategy {
    private collectionsStorage = inject(CollectionsStorageService);
    private documentsStorage = inject(GraphRagDocumentsStorageService);
    private graphRagSignal = signal<CollectionGraphRag | null>(null);
    private indexingConfigIds: number[] = [];
    private _canIndex: WritableSignal<boolean> = signal(false);
    readonly canIndex: Signal<boolean> = this._canIndex.asReadonly();

    readonly isIndexing: Signal<boolean> = computed(() => {
        const rag = this.graphRagSignal();
        if (!rag) return false;

        const status = this.collectionsStorage.getRagStatus(rag.graph_rag_id, 'graph');
        if (status != null) return status === 'processing';

        // Fallback for the brief window before the collection detail poll has
        // resolved at least once (e.g. right after the rag is created).
        const processing = this.collectionsStorage.processingConfigIds();
        return this.documentsStorage
            .documents()
            .some((d) => processing.has(d.graph_rag_document_id) && d.status !== 'completed' && d.status !== 'failed');
    });

    constructor(
        private graphRagService: GraphRagService,
        private ragIndexingService: RagIndexingService,
        private toastService: ToastService,
        private pollingService: KnowledgeSourcesPollingService
    ) {}

    create(collectionId: number, embedderId: number, llmId: number): Observable<boolean> {
        return this.graphRagService.createRagForCollection(collectionId, embedderId, llmId).pipe(
            tap((res) => this.graphRagSignal.set(res.graph_rag)),
            map(() => true)
        );
    }

    startIndexing(
        dto: CreateGraphRagIndexConfigRequest & {
            configIds?: number[];
            shouldSave?: boolean;
            pendingDeleteIds?: number[];
        }
    ): Observable<boolean> {
        const ragId = this.graphRagSignal()?.graph_rag_id;
        if (!ragId || !dto) return of(false);

        const { configIds, shouldSave, pendingDeleteIds, ...config } = dto;
        this.indexingConfigIds = configIds ?? [];
        const deleteIds = pendingDeleteIds ?? [];

        const delete$: Observable<unknown> = deleteIds.length
            ? this.documentsStorage.bulkDeleteDocuments(ragId, deleteIds)
            : of(null);

        const save$: Observable<unknown> = shouldSave
            ? this.graphRagService
                  .updateRagIndexConfigs(ragId, config)
                  .pipe(
                      tap(() =>
                          this.graphRagSignal.update((prev) =>
                              prev ? { ...prev, index_config: { ...prev.index_config, ...config } } : prev
                          )
                      )
                  )
            : of(null);

        return delete$.pipe(
            switchMap(() => save$),
            switchMap(() =>
                this.ragIndexingService.startIndexing({
                    rag_id: ragId,
                    rag_type: 'graph',
                    document_config_ids: this.indexingConfigIds,
                })
            ),
            tap(() => {
                this.toastService.success('Indexing started');
                this.collectionsStorage.markRagAsProcessing(ragId);
                this.collectionsStorage.markConfigsAsProcessing(this.indexingConfigIds);
            }),
            map(() => true)
        );
    }

    stopIndexing() {
        const ragId = this.graphRagSignal()?.graph_rag_id;
        if (!ragId) return of(false);

        return this.ragIndexingService
            .stopIndexing({
                rag_id: ragId,
                rag_type: 'graph',
            })
            .pipe(
                tap(() => {
                    this.toastService.success('Indexing stop triggered');
                    // Without this, the next poll sees these ids drop out of "processing"
                    // (because we stopped them, not because they finished) and
                    // notifyGraphRagCompletedIndexing fires a false "Indexed: X" toast —
                    // mirrors NaiveRagStrategy.stopIndexing().
                    this.pollingService.discardTrackedProcessingIds(this.indexingConfigIds);
                }),
                map(() => true)
            );
    }

    getConfigurationComponent() {
        return GraphRagConfigurationComponent;
    }

    getConfigurationInputs(): Record<string, unknown> {
        return { graphRag: this.graphRagSignal(), canIndexChange: this._canIndex };
    }
}
