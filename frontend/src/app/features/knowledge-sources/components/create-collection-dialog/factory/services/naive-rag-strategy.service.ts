import { computed, Injectable, Signal, signal, WritableSignal } from '@angular/core';
import { Observable } from 'rxjs';
import { map, tap } from 'rxjs/operators';

import { ToastService } from '../../../../../../services/notifications';
import { CreateNaiveRag } from '../../../../models/naive-rag.model';
import { CollectionsStorageService } from '../../../../services/collections-storage.service';
import { KnowledgeSourcesPollingService } from '../../../../services/knowledge-sources-polling.service';
import { NaiveRagService } from '../../../../services/naive-rag.service';
import { NaiveRagDocumentsStorageService } from '../../../../services/naive-rag-documents-storage.service';
import { RagIndexingService } from '../../../../services/rag-indexing.service';
import { NaiveRagConfigurationComponent } from '../../../naive-rag-configuration/naive-rag-configuration.component';
import { RagCreationStrategy } from '../interfaces/rag-creation-strategy.interface';

@Injectable({
    providedIn: 'root',
})
export class NaiveRagStrategy implements RagCreationStrategy {
    private naiveRag!: CreateNaiveRag;
    private _canIndex: WritableSignal<boolean> = signal(false);
    readonly canIndex: Signal<boolean> = this._canIndex.asReadonly();

    readonly isIndexing: Signal<boolean> = computed(() => {
        const processing = this.collectionsStorage.processingConfigIds();
        return this.documentsStorageService.documents().some((d) => processing.has(d.naive_rag_document_id));
    });

    constructor(
        private naiveRagService: NaiveRagService,
        private ragIndexingService: RagIndexingService,
        private documentsStorageService: NaiveRagDocumentsStorageService,
        private pollingService: KnowledgeSourcesPollingService,
        private collectionsStorage: CollectionsStorageService,
        private toastService: ToastService
    ) {}

    create(collectionId: number, embedderId: number): Observable<boolean> {
        return this.naiveRagService.createRagForCollection(collectionId, embedderId).pipe(
            tap((res) => (this.naiveRag = res.naive_rag)),
            map(() => true)
        );
    }

    startIndexing(data?: { configIds: number[] }): Observable<boolean> {
        const naiveRagId = this.naiveRag.naive_rag_id;
        const configIds =
            data?.configIds ?? this.documentsStorageService.documents().map((d) => d.naive_rag_document_id);

        return this.ragIndexingService
            .startIndexing({
                rag_id: naiveRagId,
                rag_type: 'naive',
                document_config_ids: configIds,
            })
            .pipe(
                tap(() => {
                    this.toastService.success('Indexing started');
                    this.collectionsStorage.markConfigsAsProcessing(configIds);
                }),
                map(() => true)
            );
    }

    stopIndexing() {
        const naiveRagId = this.naiveRag.naive_rag_id;
        const processing = this.collectionsStorage.processingConfigIds();
        const configIds = this.documentsStorageService
            .documents()
            .map((d) => d.naive_rag_document_id)
            .filter((id) => processing.has(id));

        return this.ragIndexingService
            .stopIndexing({
                rag_id: naiveRagId,
                rag_type: 'naive',
                document_config_ids: configIds,
            })
            .pipe(
                tap(() => {
                    this.toastService.success('Indexing stop triggered');
                    this.pollingService.discardTrackedProcessingIds(configIds);
                }),
                map(() => true)
            );
    }

    dispose(): void {
        this.pollingService.stopDocumentConfigsPolling();
    }

    getConfigurationComponent() {
        return NaiveRagConfigurationComponent;
    }

    getConfigurationInputs(): Record<string, unknown> {
        const { naive_rag_id, collection_id } = this.naiveRag;

        return { naiveRagId: naive_rag_id, collectionId: collection_id, canIndexChange: this._canIndex };
    }
}
