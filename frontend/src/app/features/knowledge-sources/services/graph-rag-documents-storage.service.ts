import { inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { Observable } from 'rxjs';
import { switchMap, tap } from 'rxjs/operators';

import { GraphRagDocument, GraphRagDocumentListResponse } from '../models/graph-rag-document.model';
import { GraphRagService } from './graph-rag.service';

@Injectable({
    providedIn: 'root',
})
export class GraphRagDocumentsStorageService implements StorageService {
    private readonly graphRagService = inject(GraphRagService);

    private documentsSignal = signal<GraphRagDocument[]>([]);
    public readonly documents = this.documentsSignal.asReadonly();

    setDocuments(documents: GraphRagDocument[]): void {
        this.documentsSignal.set(documents);
    }

    updateDocuments(fresh: GraphRagDocument[]): void {
        const byId = new Map(fresh.map((d) => [d.graph_rag_document_id, d]));
        const current = this.documentsSignal();

        const present = current
            .map((d) => byId.get(d.graph_rag_document_id) ?? d)
            .filter((d) => byId.has(d.graph_rag_document_id));

        const seen = new Set(present.map((d) => d.graph_rag_document_id));
        const added = fresh.filter((d) => !seen.has(d.graph_rag_document_id));

        this.documentsSignal.set([...present, ...added]);
    }

    fetchDocuments(ragId: number): Observable<GraphRagDocumentListResponse> {
        return this.graphRagService.getRagDocuments(ragId).pipe(tap((resp) => this.setDocuments(resp.documents)));
    }

    reIncludeFiles(ragId: number): Observable<GraphRagDocumentListResponse> {
        return this.graphRagService.reIncludeFiles(ragId).pipe(
            switchMap(() => this.graphRagService.getRagDocuments(ragId)),
            tap((resp) => this.setDocuments(resp.documents))
        );
    }

    bulkDeleteDocuments(ragId: number, documentIds: number[]): Observable<{ document_ids: number[] }> {
        return this.graphRagService.bulkDeleteDocuments(ragId, documentIds).pipe(
            tap((res) => {
                const deleted = new Set(res.document_ids);
                this.documentsSignal.update((docs) => docs.filter((d) => !deleted.has(d.document_id)));
            })
        );
    }

    clear(): void {
        this.documentsSignal.set([]);
    }
}
