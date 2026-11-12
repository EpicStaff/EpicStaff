import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import {
    CollectionGraphRag,
    CreateGraphRagForCollectionResponse,
    CreateGraphRagIndexConfigRequest,
} from '../models/graph-rag.model';
import { GraphRagDocumentListResponse } from '../models/graph-rag-document.model';
import { GraphTableData, GraphVisualizationData } from '../models/graph-visualization.model';

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

    deleteGraphRag(ragId: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${ragId}/`);
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

    bulkDeleteDocuments(ragId: number, fileIds: number[]): Observable<{ document_ids: number[] }> {
        const body = { document_ids: fileIds };
        return this.http.post<{ document_ids: number[] }>(`${this.apiUrl}${ragId}/documents/bulk-delete/`, body);
    }

    reIncludeFiles(ragId: number): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}${ragId}/documents/initialize/`, {});
    }

    getTableData(ragId: number, tableName: string, page = 1, pageSize = 10): Observable<GraphTableData> {
        const params = new HttpParams().set('page', page.toString()).set('page_size', pageSize.toString());
        return this.http.get<GraphTableData>(`${this.apiUrl}${ragId}/tables/${tableName}/`, { params });
    }

    getVisualizationData(ragId: number, maxEntities?: number, search?: string): Observable<GraphVisualizationData> {
        let params = new HttpParams();
        if (maxEntities !== undefined) {
            params = params.set('max_entities', maxEntities.toString());
        }
        if (search) {
            params = params.set('search', search);
        }
        return this.http.get<GraphVisualizationData>(`${this.apiUrl}${ragId}/visualization/`, { params });
    }

    getEntityDetails(ragId: number, entityId: string): Observable<{ description: string }> {
        return this.http.get<{ description: string }>(`${this.apiUrl}${ragId}/entity/${entityId}/`);
    }

    getRelationshipDetails(ragId: number, relationshipId: string): Observable<{ description: string }> {
        return this.http.get<{ description: string }>(`${this.apiUrl}${ragId}/relationship/${relationshipId}/`);
    }
}
