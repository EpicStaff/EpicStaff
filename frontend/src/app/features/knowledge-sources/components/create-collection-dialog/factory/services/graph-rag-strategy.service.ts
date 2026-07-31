import { computed, inject, Injectable, Signal, signal, WritableSignal } from '@angular/core';
import { Observable, of } from 'rxjs';
import { map, tap } from 'rxjs/operators';

import { ToastService } from '../../../../../../services/notifications';
import { CollectionGraphRag, CreateGraphRagIndexConfigRequest } from '../../../../models/graph-rag.model';
import { CollectionsStorageService } from '../../../../services/collections-storage.service';
import { GraphRagService } from '../../../../services/graph-rag.service';
import { RagIndexingService } from '../../../../services/rag-indexing.service';
import { GraphRagConfigurationComponent } from '../../../graph-rag-configuration/graph-rag-configuration.component';
import { RagCreationStrategy } from '../interfaces/rag-creation-strategy.interface';

@Injectable({
    providedIn: 'root',
})
export class GraphRagStrategy implements RagCreationStrategy {
    private collectionsStorage = inject(CollectionsStorageService);
    private graphRagSignal = signal<CollectionGraphRag | null>(null);
    private indexingConfigIds: number[] = [];
    private _canIndex: WritableSignal<boolean> = signal(false);
    readonly canIndex: Signal<boolean> = this._canIndex.asReadonly();

    readonly isIndexing: Signal<boolean> = computed(() => {
        const rag = this.graphRagSignal();
        if (!rag) return false;
        for (const c of this.collectionsStorage.fullCollections()) {
            const found = c.rag_configurations.find((r) => r.rag_id === rag.graph_rag_id);
            if (found) return found.status === 'processing';
        }
        return false;
    });

    constructor(
        private graphRagService: GraphRagService,
        private ragIndexingService: RagIndexingService,
        private toastService: ToastService
    ) {}

    create(collectionId: number, embedderId: number, llmId: number): Observable<boolean> {
        return this.graphRagService.createRagForCollection(collectionId, embedderId, llmId).pipe(
            tap((res) => this.graphRagSignal.set(res.graph_rag)),
            map(() => true)
        );
    }

    startIndexing(dto: CreateGraphRagIndexConfigRequest & { configIds?: number[] }): Observable<boolean> {
        const ragId = this.graphRagSignal()?.graph_rag_id;
        if (!ragId || !dto) return of(false);

        this.indexingConfigIds = dto.configIds ?? [];

        return this.ragIndexingService
            .startIndexing({
                rag_id: ragId,
                rag_type: 'graph',
                document_config_ids: this.indexingConfigIds,
            })
            .pipe(
                tap(() => {
                    this.toastService.success('Indexing started');
                    this.collectionsStorage.markRagAsProcessing(ragId);
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
                document_config_ids: this.indexingConfigIds,
            })
            .pipe(
                tap(() => this.toastService.success('Indexing stop triggered')),
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
