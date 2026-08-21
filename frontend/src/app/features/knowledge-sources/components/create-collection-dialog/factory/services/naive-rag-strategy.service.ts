import { computed, Injectable, Signal, signal, WritableSignal } from '@angular/core';
import { Observable, of } from 'rxjs';
import { map, switchMap, tap } from 'rxjs/operators';

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
    // A signal (not a plain field) so that computed()s reading it — directly, or
    // indirectly via `naiveRag` below — correctly become dirty when a rag is replaced,
    // even on a run where they short-circuited on a different signal and never read
    // this one. Mirrors GraphRagStrategy's already-correct `graphRagSignal`.
    private naiveRagSignal = signal<CreateNaiveRag | null>(null);
    private get naiveRag(): CreateNaiveRag {
        return this.naiveRagSignal()!;
    }
    private _canIndex: WritableSignal<boolean> = signal(false);
    readonly canIndex: Signal<boolean> = this._canIndex.asReadonly();

    readonly isIndexing: Signal<boolean> = computed(() => {
        const ragId = this.naiveRagSignal()?.naive_rag_id;
        const status = ragId != null ? this.collectionsStorage.getRagStatus(ragId, 'naive') : null;
        if (status != null) return status === 'processing';

        // Fallback for the brief window before the collection detail poll has
        // resolved at least once (e.g. right after the rag is created).
        const processing = this.collectionsStorage.processingConfigIds();
        return this.documentsStorageService
            .documents()
            .some(
                (d) =>
                    processing.has(d.naive_rag_document_id) &&
                    d.status !== 'completed' &&
                    d.status !== 'failed' &&
                    d.status !== 'outdated'
            );
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
            tap((res) => this.naiveRagSignal.set(res.naive_rag)),
            map(() => true)
        );
    }

    startIndexing(data?: { configIds: number[]; pendingDeleteIds?: number[] }): Observable<boolean> {
        const naiveRagId = this.naiveRag.naive_rag_id;
        const configIds =
            data?.configIds ?? this.documentsStorageService.documents().map((d) => d.naive_rag_document_id);

        // Flush the soft-delete set (if any) before indexing runs, mirroring
        // the update-flow order in `NaiveRagConfigurationDialog.runIndexing`.
        const delete$: Observable<unknown> = data?.pendingDeleteIds?.length
            ? this.documentsStorageService.bulkDeletePending(naiveRagId)
            : of(null);

        return delete$.pipe(
            switchMap(() =>
                this.ragIndexingService.startIndexing({
                    rag_id: naiveRagId,
                    rag_type: 'naive',
                    document_config_ids: configIds,
                })
            ),
            tap(() => {
                this.toastService.success('Indexing started');
                this.collectionsStorage.markConfigsAsProcessing(configIds);
                this.collectionsStorage.markRagAsProcessing(naiveRagId);
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
