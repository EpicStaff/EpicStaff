import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { extractHttpErrorMessage } from '@shared/utils';
import { forkJoin, Observable, of, ReplaySubject } from 'rxjs';
import { catchError, finalize, map, switchMap, tap } from 'rxjs/operators';

import { ToastService } from '../../../services/notifications';
import { buildStorageImportSummary, extractStorageFileIds, formatSkippedReasons } from '../helpers/storage-import.util';
import {
    CollectionDocument,
    CopyDocumentsResponse,
    DisplayedListDocument,
    ImportFromStorageErrorResponse,
    ImportFromStorageResponse,
    StorageImportCandidate,
    UploadDocumentResponse,
} from '../models/document.model';
import { CollectionsApiService } from './collections-api.service';
import { CollectionsStorageService } from './collections-storage.service';
import { DocumentsApiService } from './documents-api.service';

@Injectable({
    providedIn: 'root',
})
export class DocumentsStorageService implements StorageService {
    private documentsSignal = signal<CollectionDocument[]>([]);
    private documentsLoaded = signal<boolean>(false);
    private uploadingDocumentsSignal = signal<DisplayedListDocument[]>([]);
    private deletingDocumentIdsSignal = signal(new Set<number>());
    /** In-flight import count per collection, so overlapping imports into one collection do not clear each other. */
    private importCountsByCollectionSignal = signal<ReadonlyMap<number, number>>(new Map<number, number>());
    public readonly documents = this.documentsSignal.asReadonly();
    public readonly isDocumentsLoaded = this.documentsLoaded.asReadonly();
    public readonly uploadingDocuments = this.uploadingDocumentsSignal.asReadonly();

    private readonly documentsApiService = inject(DocumentsApiService);
    private readonly collectionsApiService = inject(CollectionsApiService);
    private readonly collectionsStorageService = inject(CollectionsStorageService);
    private readonly toastService = inject(ToastService);
    /** Collections whose full document list was fetched — including empty ones, which leave no trace in the cache. */
    private readonly fetchedCollectionIds = new Set<number>();

    uploadDocuments(
        collectionId: number,
        files: File[],
        placeholders?: DisplayedListDocument[]
    ): Observable<UploadDocumentResponse | undefined> {
        if (placeholders?.length) {
            this.uploadingDocumentsSignal.update((docs) => [...docs, ...placeholders]);
        }

        return this.documentsApiService.uploadDocuments(collectionId, files).pipe(
            tap((resp: UploadDocumentResponse) => {
                const { documents } = resp;
                this.addDocumentsToCache(documents);
                this.toastService.success('Documents uploaded successfully');
            }),
            catchError(() => {
                this.toastService.error('Failed to upload documents');
                return of();
            }),
            finalize(() => {
                if (placeholders?.length) {
                    const names = new Set(placeholders.map((p) => p.file_name));
                    this.uploadingDocumentsSignal.update((docs) =>
                        docs.filter((d) => !(d.source_collection === collectionId && names.has(d.file_name)))
                    );
                }
            })
        );
    }

    getDocumentsByCollectionId(collectionId: number): Observable<CollectionDocument[]> {
        const cached = this.documentsSignal().filter((d) => d.source_collection === collectionId);
        if (!cached.length) {
            return this.collectionsApiService.getDocumentsByCollectionId(collectionId).pipe(
                map(({ documents }) => {
                    return documents.map((doc) => ({
                        ...doc,
                        source_collection: collectionId,
                    }));
                }),
                tap((docs) => {
                    this.fetchedCollectionIds.add(collectionId);
                    this.addDocumentsToCache(docs);
                })
            );
        }

        return of(cached);
    }

    copyDocumentsToCollections(documentIds: number[], collectionIds: number[]): Observable<CopyDocumentsResponse[]> {
        const requests = collectionIds.map((collection_id) =>
            this.documentsApiService.copyDocuments({ collection_id, document_ids: documentIds })
        );

        return forkJoin(requests).pipe(
            tap((responses) => {
                const allDocs = responses.flatMap((r) => r.documents);
                this.addDocumentsToCache(allDocs);
                this.toastService.success('Documents copied successfully');
            }),
            catchError(() => {
                this.toastService.error('Failed to copy documents');
                return of([]);
            })
        );
    }

    /**
     * Imports storage files/folders into a collection and toasts the outcome: the imported/skipped
     * summary, or the server error (403 is already toasted by `forbiddenInterceptor`).
     *
     * The request is subscribed here, in this root service, so it outlives the component that
     * started it: unsubscribing from the returned observable never cancels an import the server
     * may already have accepted. Emits the response, or `null` when nothing was sent or it failed.
     */
    importFromStorage(
        collectionId: number,
        items: StorageImportCandidate[]
    ): Observable<ImportFromStorageResponse | null> {
        const { storageFileIds, missingCount } = extractStorageFileIds(items);
        if (storageFileIds.length === 0) {
            this.toastService.error('None of the selected items could be added');
            return of(null);
        }
        if (missingCount > 0) {
            this.toastService.warning(`${missingCount} item(s) could not be added`);
        }

        const result = new ReplaySubject<ImportFromStorageResponse | null>(1);
        this.adjustImportCount(collectionId, 1);
        this.requestImport(collectionId, storageFileIds)
            .pipe(finalize(() => this.adjustImportCount(collectionId, -1)))
            .subscribe(result);
        return result.asObservable();
    }

    isImporting(collectionId: number): boolean {
        return (this.importCountsByCollectionSignal().get(collectionId) ?? 0) > 0;
    }

    isDeleting(documentId: number | undefined): boolean {
        return !!documentId && this.deletingDocumentIdsSignal().has(documentId);
    }

    deleteDocument(documentId: number): Observable<boolean> {
        this.deletingDocumentIdsSignal.update((ids) => new Set(ids).add(documentId));

        return this.documentsApiService.deleteDocumentById(documentId).pipe(
            tap(() => {
                this.toastService.success('Document deleted');
                this.deleteDocumentFromCache(documentId);
            }),
            map(() => true),
            catchError(() => {
                this.toastService.error('Failed to delete document');
                return of(false);
            }),
            finalize(() => {
                this.deletingDocumentIdsSignal.update((ids) => {
                    const next = new Set(ids);
                    next.delete(documentId);
                    return next;
                });
            })
        );
    }

    private addDocumentsToCache(documents: CollectionDocument[]) {
        this.documentsSignal.update((currentDocs) => {
            const existingIds = new Set(currentDocs.map((d) => d.document_id));
            const newDocs = documents.filter((d) => !existingIds.has(d.document_id));
            return [...currentDocs, ...newDocs];
        });

        const affectedIds = [...new Set(documents.map((d) => d.source_collection))];
        for (const collectionId of affectedIds) {
            const count = this.documentsSignal().filter((d) => d.source_collection === collectionId).length;
            this.collectionsStorageService.updateDocumentCount(collectionId, count);
        }
    }

    refreshDocumentsByCollectionId(collectionId: number): Observable<CollectionDocument[]> {
        return this.collectionsApiService.getDocumentsByCollectionId(collectionId).pipe(
            map(({ documents }) => documents.map((doc) => ({ ...doc, source_collection: collectionId }))),
            tap((docs) => {
                this.fetchedCollectionIds.add(collectionId);
                this.documentsSignal.update((current) => [
                    ...current.filter((d) => d.source_collection !== collectionId),
                    ...docs,
                ]);
            }),
            catchError(() => of([]))
        );
    }

    clear(): void {
        this.documentsSignal.set([]);
        this.documentsLoaded.set(false);
        this.fetchedCollectionIds.clear();
    }

    private adjustImportCount(collectionId: number, delta: number): void {
        this.importCountsByCollectionSignal.update((counts) => {
            const next = new Map(counts);
            const count = (next.get(collectionId) ?? 0) + delta;
            if (count > 0) {
                next.set(collectionId, count);
            } else {
                next.delete(collectionId);
            }
            return next;
        });
    }

    private requestImport(
        collectionId: number,
        storageFileIds: number[]
    ): Observable<ImportFromStorageResponse | null> {
        return this.documentsApiService.importFromStorage(collectionId, storageFileIds).pipe(
            tap((response) => {
                this.mergeImportedDocuments(collectionId, response.documents);
                const summary = buildStorageImportSummary(response);
                if (summary.kind === 'success') {
                    this.toastService.success(summary.message);
                } else {
                    this.toastService.warning(summary.message);
                }
            }),
            // Authoritative document_count / status / rag configs for the collection.
            switchMap((response) =>
                this.collectionsStorageService.getFullCollection(collectionId, true).pipe(
                    catchError(() => of(null)),
                    map(() => response)
                )
            ),
            catchError((error: unknown) => {
                this.notifyImportError(error);
                return of(null);
            })
        );
    }

    /**
     * Only merge when the collection's documents are already cached: a partial cache would make
     * `getDocumentsByCollectionId` return just the imported documents instead of fetching all.
     * A fetched-but-empty collection counts as cached, so importing into the open, empty
     * collection shows the new documents right away.
     */
    private mergeImportedDocuments(collectionId: number, documents: CollectionDocument[]): void {
        const isCollectionCached =
            this.fetchedCollectionIds.has(collectionId) ||
            this.documentsSignal().some((d) => d.source_collection === collectionId);
        if (!isCollectionCached || documents.length === 0) return;
        this.addDocumentsToCache(documents.map((doc) => ({ ...doc, source_collection: collectionId })));
    }

    private notifyImportError(error: unknown): void {
        if (!(error instanceof HttpErrorResponse)) {
            this.toastService.error('Failed to add files to the collection');
            return;
        }
        if (error.status === 403) return;
        const message = extractHttpErrorMessage(error, 'Failed to add files to the collection');
        const skipped =
            error.status === 400 ? (error.error as ImportFromStorageErrorResponse | null)?.skipped : undefined;
        this.toastService.error(skipped?.length ? `${message} (skipped: ${formatSkippedReasons(skipped)})` : message);
    }

    private deleteDocumentFromCache(id: number) {
        const doc = this.documentsSignal().find((d) => d.document_id === id);
        this.documentsSignal.update((docs) => docs.filter((d) => d.document_id !== id));

        if (doc) {
            const count = this.documentsSignal().filter((d) => d.source_collection === doc.source_collection).length;
            this.collectionsStorageService.updateDocumentCount(doc.source_collection, count);
        }
    }
}
