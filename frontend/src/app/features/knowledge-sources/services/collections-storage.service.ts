import { inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { catchError, delay, Observable, of, Subject, tap, throwError } from 'rxjs';
import { shareReplay } from 'rxjs/operators';

import {
    CreateCollectionDtoResponse,
    DeleteCollectionResponse,
    GetCollectionRequest,
} from '../models/collection.model';
import { CollectionDetailsGraphRag } from '../models/graph-rag.model';
import { CollectionDetailsNaiveRag } from '../models/naive-rag.model';
import { CollectionsApiService } from './collections-api.service';

@Injectable({
    providedIn: 'root',
})
export class CollectionsStorageService implements StorageService {
    // List of collection preview
    private collectionsSignal = signal<GetCollectionRequest[]>([]);
    private collectionsLoaded = signal<boolean>(false);
    public readonly collections = this.collectionsSignal.asReadonly();
    public readonly isCollectionsLoaded = this.collectionsLoaded.asReadonly();

    // List of collection details
    private fullCollectionsSignal = signal<CreateCollectionDtoResponse[]>([]);
    private fullCollectionsLoaded = signal<boolean>(false);
    public readonly fullCollections = this.fullCollectionsSignal.asReadonly();
    // public readonly isFullCollectionsLoaded = this.fullCollectionsLoaded.asReadonly();

    // Config ids currently indexing/queued: rebuilt from polled collection data,
    // set immediately on run indexing for instant spinners.
    private processingConfigIdsSignal = signal<Set<number>>(new Set());
    public readonly processingConfigIds = this.processingConfigIdsSignal.asReadonly();

    readonly collectionDeleted$ = new Subject<number>();

    markConfigsAsProcessing(configIds: number[]): void {
        this.processingConfigIdsSignal.update((ids) => new Set([...ids, ...configIds]));
    }

    // Optimistically sets the given rag's status to 'processing' in the fullCollections cache.
    // Polling will overwrite on next tick.
    markRagAsProcessing(ragId: number): void {
        this.fullCollectionsSignal.update((collections) =>
            collections.map((c) => ({
                ...c,
                rag_configurations: c.rag_configurations.map((r) =>
                    r.rag_id === ragId ? { ...r, status: 'processing' } : r
                ),
            }))
        );
    }

    private rebuildProcessingConfigIds(): void {
        this.processingConfigIdsSignal.set(
            new Set(
                this.fullCollectionsSignal().flatMap((c) =>
                    c.rag_configurations.flatMap((r) => {
                        if (r.rag_type === 'naive') {
                            return (r as CollectionDetailsNaiveRag).indexing_document_config_ids;
                        }
                        if (r.rag_type === 'graph') {
                            return (r as CollectionDetailsGraphRag).processing_document_ids ?? [];
                        }
                        return [];
                    })
                )
            )
        );
    }

    private readonly collectionsApiService = inject(CollectionsApiService);

    createCollection(): Observable<CreateCollectionDtoResponse> {
        return this.collectionsApiService.createCollection().pipe(
            tap((newCollection: CreateCollectionDtoResponse) => {
                this.updateOrCreateCollectionInCache(newCollection);
            }),
            catchError((err) => throwError(() => err))
        );
    }

    getCollections(forceRefresh = false): Observable<GetCollectionRequest[]> {
        if (this.collectionsLoaded() && !forceRefresh) {
            return of(this.collectionsSignal());
        }
        return this.collectionsApiService.getCollections().pipe(
            tap((collections) => {
                this.setCollections(collections);
            }),
            delay(this.collectionsLoaded() ? 0 : 300),
            shareReplay(1),
            catchError((err) => {
                this.collectionsLoaded.set(false);
                return throwError(() => err);
            })
        );
    }

    setCollections(collections: GetCollectionRequest[]) {
        this.collectionsSignal.set(collections);
        this.collectionsLoaded.set(true);
    }

    getFullCollection(id: number, forceRefresh = false): Observable<CreateCollectionDtoResponse | null> {
        const cachedCollection = this.fullCollectionsSignal().find((c) => c.collection_id === id);
        if (cachedCollection && !forceRefresh) {
            return of(cachedCollection);
        }

        return this.collectionsApiService.getCollectionById(id).pipe(
            tap((collection: CreateCollectionDtoResponse) => {
                this.updateOrCreateCollectionInCache(collection);
            }),
            delay(this.fullCollectionsLoaded() ? 0 : 300),
            catchError((err) => throwError(() => err))
        );
    }

    updateCollectionById(
        id: number,
        body: Partial<CreateCollectionDtoResponse>
    ): Observable<CreateCollectionDtoResponse> {
        return this.collectionsApiService.updateCollectionById(id, body).pipe(
            tap((updated) => {
                this.updateOrCreateCollectionInCache(updated);
            }),
            catchError((err) => throwError(() => err))
        );
    }

    deleteCollectionById(id: number): Observable<DeleteCollectionResponse> {
        return this.collectionsApiService.deleteCollectionById(id).pipe(
            tap(() => {
                // this.toastService.success('Collection deleted');
                this.deleteCollectionFromCache(id);
            }),
            catchError((err) => throwError(() => err))
        );
    }

    updateDocumentCount(collectionId: number, newCount: number): void {
        this.collectionsSignal.update((collections) => {
            const index = collections.findIndex((c) => c.collection_id === collectionId);
            if (index < 0) return collections;
            const updated = [...collections];
            updated[index] = { ...updated[index], document_count: newCount };
            return updated;
        });

        this.fullCollectionsSignal.update((collections) => {
            const index = collections.findIndex((c) => c.collection_id === collectionId);
            if (index < 0) return collections;
            const updated = [...collections];
            updated[index] = { ...updated[index], document_count: newCount };
            return updated;
        });
    }

    updateOrCreateCollectionInCache(updated: CreateCollectionDtoResponse): void {
        const { rag_configurations, ...rest } = updated;

        this.collectionsSignal.update((collections) => {
            const index = collections.findIndex((c) => c.collection_id === rest.collection_id);
            if (index >= 0) {
                collections[index] = {
                    ...collections[index],
                    ...rest,
                    rag_configurations: rag_configurations ?? collections[index].rag_configurations,
                };
            } else {
                collections.push({ ...rest, rag_configurations: rag_configurations ?? [] });
            }
            return [...collections];
        });

        this.fullCollectionsSignal.update((collections) => {
            const index = collections.findIndex((c) => c.collection_id === updated.collection_id);
            if (index >= 0) {
                collections[index] = updated;
            } else {
                collections.push(updated);
            }
            return [...collections];
        });

        this.rebuildProcessingConfigIds();
    }

    clear(): void {
        this.collectionsSignal.set([]);
        this.collectionsLoaded.set(false);
        this.fullCollectionsSignal.set([]);
        this.fullCollectionsLoaded.set(false);
        this.processingConfigIdsSignal.set(new Set());
    }

    private deleteCollectionFromCache(id: number) {
        this.collectionDeleted$.next(id);

        const currentCollections = this.collectionsSignal();
        const updatedCollections = currentCollections.filter((p) => p.collection_id !== id);
        this.collectionsSignal.set(updatedCollections);

        const currentFullCollections = this.fullCollectionsSignal();
        const updatedFullCollections = currentFullCollections.filter((p) => p.collection_id !== id);
        this.fullCollectionsSignal.set(updatedFullCollections);
    }
}
