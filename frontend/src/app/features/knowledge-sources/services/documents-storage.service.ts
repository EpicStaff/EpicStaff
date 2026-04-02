import { inject, Injectable, signal } from '@angular/core';
import { Observable, of } from 'rxjs';
import { catchError, map, tap } from 'rxjs/operators';

import { ToastService } from '../../../services/notifications/toast.service';
import { CollectionDocument, DeleteDocumentResponse, UploadDocumentResponse } from '../models/document.model';
import { CollectionsApiService } from './collections-api.service';
import { DocumentsApiService } from './documents-api.service';

@Injectable({
    providedIn: 'root',
})
export class DocumentsStorageService {
    private documentsSignal = signal<CollectionDocument[]>([]);
    private documentsLoaded = signal<boolean>(false);
    public readonly documents = this.documentsSignal.asReadonly();
    public readonly isDocumentsLoaded = this.documentsLoaded.asReadonly();

    private readonly documentsApiService = inject(DocumentsApiService);
    private readonly collectionsApiService = inject(CollectionsApiService);
    private readonly toastService = inject(ToastService);

    uploadDocuments(collectionId: number, files: File[]): Observable<UploadDocumentResponse | undefined> {
        return this.documentsApiService.uploadDocuments(collectionId, files).pipe(
            tap((resp: UploadDocumentResponse) => {
                const { documents } = resp;
                this.addDocumentsToCache(documents);
                this.toastService.success('Documents uploaded successfully');
            }),
            catchError(() => {
                this.toastService.error('Failed to upload documents');
                return of();
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

    deleteDocumentById(id: number): Observable<DeleteDocumentResponse | undefined> {
        return this.documentsApiService.deleteDocumentById(id).pipe(
            tap(() => {
                this.toastService.success('Document deleted');
                this.deleteDocumentFromCache(id);
            }),
            catchError(() => {
                this.toastService.error('Failed to delete document');
                return of();
            })
        );
    }

    private addDocumentsToCache(documents: CollectionDocument[]) {
        this.documentsSignal.update((currentDocs) => {
            const existingIds = new Set(currentDocs.map((d) => d.document_id));

            const newDocs = documents.filter((d) => !existingIds.has(d.document_id));

            return [...currentDocs, ...newDocs];
        });
    }

    private deleteDocumentFromCache(id: number) {
        const currentDocuments = this.documentsSignal();
        const updatedDocuments = currentDocuments.filter((d) => d.document_id !== id);
        this.documentsSignal.set(updatedDocuments);
    }
}
