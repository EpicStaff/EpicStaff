import { inject, Injectable } from '@angular/core';
import { forkJoin, Observable, of, Subscription, timer } from 'rxjs';
import { catchError, filter, repeat, switchMap, takeUntil, tap } from 'rxjs/operators';

import { ToastService } from '../../../services/notifications';
import { GraphRagDocument } from '../models/graph-rag-document.model';
import { NaiveRagDocumentConfig } from '../models/naive-rag-document.model';
import { CollectionsApiService } from './collections-api.service';
import { CollectionsStorageService } from './collections-storage.service';
import { DocumentsStorageService } from './documents-storage.service';
import { GraphRagService } from './graph-rag.service';
import { GraphRagDocumentsStorageService } from './graph-rag-documents-storage.service';
import { NaiveRagService } from './naive-rag.service';
import { NaiveRagDocumentsStorageService } from './naive-rag-documents-storage.service';

const POLL_INTERVAL_MS = 5_000;

@Injectable({
    providedIn: 'root',
})
export class KnowledgeSourcesPollingService {
    private collectionsApiService = inject(CollectionsApiService);
    private collectionsStorage = inject(CollectionsStorageService);
    private documentsStorage = inject(DocumentsStorageService);
    private naiveRagService = inject(NaiveRagService);
    private naiveRagDocumentsStorage = inject(NaiveRagDocumentsStorageService);
    private graphRagService = inject(GraphRagService);
    private graphRagDocumentsStorage = inject(GraphRagDocumentsStorageService);
    private toastService = inject(ToastService);

    private pagePollingSub: Subscription | null = null;
    private activeConfigsRagId: number | null = null;
    private activeGraphRagId: number | null = null;
    private trackedProcessing = new Map<number, { processedAt: string | null; failedAt: string | null }>();
    private trackedGraphProcessing = new Set<number>();

    // timer + repeat: the next 5s countdown starts only after the previous refresh fully finished.
    // takeUntil(collectionDeleted$): if a collection is deleted during an in-flight tick, drop the
    // tick entirely so its stale taps can't re-add the just-deleted collection to the cache.
    startPagePolling(): void {
        this.stopPagePolling();
        this.pagePollingSub = timer(POLL_INTERVAL_MS)
            .pipe(
                filter(() => document.visibilityState === 'visible'),
                switchMap(() =>
                    this.refreshAll(this.collectionsStorage.selectedCollectionId()).pipe(
                        takeUntil(this.collectionsStorage.collectionDeleted$)
                    )
                ),
                repeat()
            )
            .subscribe();
    }

    stopPagePolling(): void {
        this.pagePollingSub?.unsubscribe();
        this.pagePollingSub = null;
    }

    // Registers the naive rag whose document configs are refreshed on the shared tick.
    startDocumentConfigsPolling(ragId: number): void {
        this.trackedProcessing = new Map();
        this.activeConfigsRagId = ragId;
    }

    stopDocumentConfigsPolling(): void {
        this.activeConfigsRagId = null;
    }

    // Registers the graph rag whose documents are refreshed on the shared tick.
    startGraphRagDocumentsPolling(ragId: number): void {
        this.trackedGraphProcessing = new Set();
        this.activeGraphRagId = ragId;
    }

    stopGraphRagDocumentsPolling(): void {
        this.activeGraphRagId = null;
    }

    discardTrackedProcessingIds(configIds: number[]): void {
        for (const id of configIds) {
            this.trackedProcessing.delete(id);
            this.trackedGraphProcessing.delete(id);
        }
    }

    // All requests run in parallel; collection details and document configs are applied
    // together in one synchronous commit so spinners and statuses swap in the same frame.
    private refreshAll(selectedId: number | null): Observable<unknown> {
        const collections$ = this.collectionsApiService.getCollections().pipe(
            tap((collections) => this.collectionsStorage.setCollections(collections)),
            catchError(() => of(null))
        );

        if (!selectedId || !this.collectionsStorage.collections().some((c) => c.collection_id === selectedId)) {
            return collections$;
        }

        const ragId = this.activeConfigsRagId;
        const graphRagId = this.activeGraphRagId;

        return forkJoin({
            collections: collections$,
            documents: this.documentsStorage
                .refreshDocumentsByCollectionId(selectedId)
                .pipe(catchError(() => of(null))),
            fullCollection: this.collectionsApiService.getCollectionById(selectedId).pipe(catchError(() => of(null))),
            configsResponse: ragId
                ? this.naiveRagService.getDocumentConfigs(ragId).pipe(catchError(() => of(null)))
                : of(null),
            graphDocsResponse: graphRagId
                ? this.graphRagService.getRagDocuments(graphRagId).pipe(catchError(() => of(null)))
                : of(null),
        }).pipe(
            tap(({ fullCollection, configsResponse, graphDocsResponse }) => {
                if (fullCollection) {
                    this.collectionsStorage.updateOrCreateCollectionInCache(fullCollection);
                }
                if (configsResponse) {
                    this.naiveRagDocumentsStorage.updateDocumentsFromConfigs(configsResponse.configs);
                    this.notifyCompletedIndexing(configsResponse.configs);
                }
                if (graphDocsResponse) {
                    this.graphRagDocumentsStorage.updateDocuments(graphDocsResponse.documents);
                    this.notifyGraphRagCompletedIndexing(graphDocsResponse.documents);
                }
            })
        );
    }

    private notifyCompletedIndexing(configs: NaiveRagDocumentConfig[]): void {
        const processing = this.collectionsStorage.processingConfigIds();

        for (const config of configs) {
            const id = config.naive_rag_document_id;
            const tracked = this.trackedProcessing.get(id);

            if (processing.has(id)) {
                if (!tracked) {
                    this.trackedProcessing.set(id, {
                        processedAt: config.processed_at,
                        failedAt: config.failed_at,
                    });
                }
                continue;
            }

            if (!tracked) continue;
            this.trackedProcessing.delete(id);

            const cancelled = tracked.processedAt === config.processed_at && tracked.failedAt === config.failed_at;
            if (cancelled) continue;

            if (config.status === 'failed') {
                this.toastService.error(`Indexing ${config.file_name} failed: ${config.error_message}`);
            } else {
                this.toastService.success(`Indexed: ${config.file_name}`);
            }
        }
    }

    private notifyGraphRagCompletedIndexing(documents: GraphRagDocument[]): void {
        const processing = this.collectionsStorage.processingConfigIds();

        for (const doc of documents) {
            const id = doc.graph_rag_document_id;
            const wasTracked = this.trackedGraphProcessing.has(id);

            if (processing.has(id)) {
                if (!wasTracked) this.trackedGraphProcessing.add(id);
                continue;
            }

            if (!wasTracked) continue;
            this.trackedGraphProcessing.delete(id);

            if (doc.status === 'failed') {
                this.toastService.error(`Indexing ${doc.file_name} failed`);
            } else {
                this.toastService.success(`Indexed: ${doc.file_name}`);
            }
        }
    }
}
