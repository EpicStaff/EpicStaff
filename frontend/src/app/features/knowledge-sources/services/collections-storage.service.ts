import { inject, Injectable, signal } from '@angular/core';
import { catchError, delay, Observable, of, tap, throwError } from 'rxjs';
import { shareReplay } from 'rxjs/operators';

import {
    CreateCollectionDtoResponse,
    DeleteCollectionResponse,
    GetCollectionRequest,
} from '../models/collection.model';
import { CollectionsApiService } from './collections-api.service';

@Injectable({
    providedIn: 'root',
})
export class CollectionsStorageService {
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

    private updateOrCreateCollectionInCache(updated: CreateCollectionDtoResponse): void {
        const rest = { ...updated };
        delete (rest as Record<string, unknown>)['rag_configurations'];

        this.collectionsSignal.update((collections) => {
            const index = collections.findIndex((c) => c.collection_id === rest.collection_id);
            if (index >= 0) {
                collections[index] = rest;
            } else {
                collections.push(rest);
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

    private deleteCollectionFromCache(id: number) {
        const currentCollections = this.collectionsSignal();
        const updatedCollections = currentCollections.filter((p) => p.collection_id !== id);
        this.collectionsSignal.set(updatedCollections);

        const currentFullCollections = this.fullCollectionsSignal();
        const updatedFullCollections = currentFullCollections.filter((p) => p.collection_id !== id);
        this.fullCollectionsSignal.set(updatedFullCollections);
    }
}
