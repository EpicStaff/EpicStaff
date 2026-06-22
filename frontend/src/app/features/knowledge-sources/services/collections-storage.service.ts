import { inject, Injectable, Injector, Signal, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { catchError, delay, EMPTY, interval, Observable, of, Subscription, tap, throwError } from 'rxjs';
import { exhaustMap, filter, shareReplay, switchMap } from 'rxjs/operators';

import {
    CreateCollectionDtoResponse,
    DeleteCollectionResponse,
    GetCollectionRequest,
} from '../models/collection.model';
import { CollectionsApiService } from './collections-api.service';
import { DocumentsStorageService } from './documents-storage.service';

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

    private readonly collectionsApiService = inject(CollectionsApiService);
    private readonly injector = inject(Injector);
    private pollingSubscription: Subscription | null = null;
    private static readonly POLL_INTERVAL_MS = 5_000;

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

    private updateOrCreateCollectionInCache(updated: CreateCollectionDtoResponse): void {
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
    }

    private selectedCollectionId: Signal<number | null> | null = null;

    startPolling(selectedCollectionId: Signal<number | null>): void {
        this.stopPolling();
        this.selectedCollectionId = selectedCollectionId;

        this.pollingSubscription = interval(CollectionsStorageService.POLL_INTERVAL_MS)
            .pipe(
                filter(() => document.visibilityState === 'visible'),
                exhaustMap(() => this.refreshAll())
            )
            .subscribe();
    }

    stopPolling(): void {
        this.pollingSubscription?.unsubscribe();
        this.pollingSubscription = null;
        this.selectedCollectionId = null;
    }

    private refreshAll(): Observable<unknown> {
        const collections$ = this.collectionsApiService.getCollections().pipe(
            tap((collections) => this.setCollections(collections)),
            catchError(() => EMPTY)
        );

        const selectedId = this.selectedCollectionId?.();
        if (!selectedId) {
            return collections$;
        }

        if (!this.collectionsSignal().some((c) => c.collection_id === selectedId)) {
            return collections$;
        }

        const fullCollection$ = this.collectionsApiService.getCollectionById(selectedId).pipe(
            tap((collection) => this.updateOrCreateCollectionInCache(collection)),
            catchError(() => EMPTY)
        );

        const documentsStorageService = this.injector.get(DocumentsStorageService);
        const documents$ = documentsStorageService
            .refreshDocumentsByCollectionId(selectedId)
            .pipe(catchError(() => EMPTY));

        return collections$.pipe(
            switchMap(() => fullCollection$),
            switchMap(() => documents$)
        );
    }

    clear(): void {
        this.collectionsSignal.set([]);
        this.collectionsLoaded.set(false);
        this.fullCollectionsSignal.set([]);
        this.fullCollectionsLoaded.set(false);
    }

    private deleteCollectionFromCache(id: number) {
        const currentCollections = this.collectionsSignal();
        const updatedCollections = currentCollections.filter((p) => p.collection_id !== id);
        this.collectionsSignal.set(updatedCollections);

        const currentFullCollections = this.fullCollectionsSignal();
        const updatedFullCollections = currentFullCollections.filter((p) => p.collection_id !== id);
        this.fullCollectionsSignal.set(updatedFullCollections);
    }
}
