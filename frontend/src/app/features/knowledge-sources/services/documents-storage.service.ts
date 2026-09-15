import { inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { forkJoin, Observable, of } from 'rxjs';
import { catchError, finalize, map, tap } from 'rxjs/operators';

import { ToastService } from '../../../services/notifications/toast.service';
import {
    CollectionDocument,
    CopyDocumentsResponse,
    DisplayedListDocument,
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
    public readonly documents = this.documentsSignal.asReadonly();
    public readonly isDocumentsLoaded = this.documentsLoaded.asReadonly();
    public readonly uploadingDocuments = this.uploadingDocumentsSignal.asReadonly();

    private readonly documentsApiService = inject(DocumentsApiService);
    private readonly collectionsApiService = inject(CollectionsApiService);
    private readonly collectionsStorageService = inject(CollectionsStorageService);
    private readonly toastService = inject(ToastService);

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
                tap((docs) => this.addDocumentsToCache(docs))
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
