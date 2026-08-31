import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import {
    CollectionGraphRag,
    CreateGraphRagForCollectionResponse,
    CreateGraphRagIndexConfigRequest,
} from '../models/graph-rag.model';
import { GraphRagDocumentListResponse } from '../models/graph-rag-document.model';

@Injectable({
    providedIn: 'root',
})
export class GraphRagService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    private readonly httpHeaders = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    private get apiUrl(): string {
        return `${this.configService.apiUrl}graph-rag/`;
    }

    createRagForCollection(
        collectionId: number,
        embedderId: number,
        llmId: number
    ): Observable<CreateGraphRagForCollectionResponse> {
        const body = { embedder_id: embedderId, llm_id: llmId };

        return this.http.post<CreateGraphRagForCollectionResponse>(
            `${this.apiUrl}collections/${collectionId}/graph-rag/`,
            body
        );
    }

    getRagById(ragId: number): Observable<CollectionGraphRag> {
        return this.http.get<CollectionGraphRag>(`${this.apiUrl}${ragId}/`);
    }

    getRagDocuments(ragId: number): Observable<GraphRagDocumentListResponse> {
        return this.http.get<GraphRagDocumentListResponse>(`${this.apiUrl}${ragId}/documents/list/`);
    }

    updateRagIndexConfigs(
        ragId: number,
        dto: CreateGraphRagIndexConfigRequest
    ): Observable<CreateGraphRagIndexConfigRequest> {
        return this.http.put<CreateGraphRagIndexConfigRequest>(`${this.apiUrl}${ragId}/index-config/`, dto);
    }

    deleteFileById(ragId: number, fileId: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${ragId}/documents/${fileId}/`);
    }

    deleteGraphRag(ragId: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${ragId}/`);
    }

    bulkDeleteDocuments(ragId: number, fileIds: number[]): Observable<{ document_ids: number[] }> {
        const body = { document_ids: fileIds };
        return this.http.post<{ document_ids: number[] }>(`${this.apiUrl}${ragId}/documents/bulk-delete/`, body);
    }

    reIncludeFiles(ragId: number): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}${ragId}/documents/initialize/`, {});
    }
}
