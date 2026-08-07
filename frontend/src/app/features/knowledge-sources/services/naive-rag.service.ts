import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { CreateNaiveRagForCollectionResponse, DeleteNaiveRagResponse } from '../models/naive-rag.model';
import {
    CancelNaiveNaiveRagChunkingResponse,
    ChunkSearchResponse,
    GetChunksByIdsResponse,
    GetNaiveRagDocumentChunksResponse,
    NaiveRagChunkingResponse,
} from '../models/naive-rag-chunk.model';
import {
    BulkDeleteNaiveRagDocumentDtoRequest,
    BulkDeleteNaiveRagDocumentDtoResponse,
    BulkUpdateNaiveRagDocumentDtoResponse,
    BulkUpdateNaiveRagDocumentsRequest,
    GetNaiveRagDocumentConfigsResponse,
    InitNaiveRagDocumentsResponse,
    RunNaiveRagDocumentChunkingRequest,
} from '../models/naive-rag-document.model';

@Injectable({
    providedIn: 'root',
})
export class NaiveRagService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    private readonly httpHeaders = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    private get apiUrl(): string {
        return `${this.configService.apiUrl}naive-rag/`;
    }

    createRagForCollection(collectionId: number, embedderId: number): Observable<CreateNaiveRagForCollectionResponse> {
        const body = { embedder_id: embedderId };

        return this.http.post<CreateNaiveRagForCollectionResponse>(
            `${this.apiUrl}collections/${collectionId}/naive-rag/`,
            body
        );
    }

    deleteNaiveRag(ragId: number): Observable<DeleteNaiveRagResponse> {
        return this.http.delete<DeleteNaiveRagResponse>(`${this.apiUrl}${ragId}/`);
    }

    getDocumentConfigs(naiveRagId: number): Observable<GetNaiveRagDocumentConfigsResponse> {
        return this.http.get<GetNaiveRagDocumentConfigsResponse>(`${this.apiUrl}${naiveRagId}/document-configs/`);
    }

    bulkUpdateDocumentConfigs(
        ragId: number,
        dto: BulkUpdateNaiveRagDocumentsRequest[]
    ): Observable<BulkUpdateNaiveRagDocumentDtoResponse> {
        return this.http.put<BulkUpdateNaiveRagDocumentDtoResponse>(
            `${this.apiUrl}${ragId}/document-configs/bulk-update/`,
            dto
        );
    }

    bulkDeleteDocumentConfigs(
        ragId: number,
        dto: BulkDeleteNaiveRagDocumentDtoRequest
    ): Observable<BulkDeleteNaiveRagDocumentDtoResponse> {
        return this.http.post<BulkDeleteNaiveRagDocumentDtoResponse>(
            `${this.apiUrl}${ragId}/document-configs/bulk-delete/`,
            dto
        );
    }

    initializeDocuments(ragId: number): Observable<InitNaiveRagDocumentsResponse> {
        return this.http.post<InitNaiveRagDocumentsResponse>(`${this.apiUrl}${ragId}/document-configs/initialize/`, {});
    }

    runChunkingProcess(
        ragId: number,
        documentId: number,
        body: RunNaiveRagDocumentChunkingRequest
    ): Observable<NaiveRagChunkingResponse> {
        return this.http.post<NaiveRagChunkingResponse>(
            `${this.apiUrl}${ragId}/document-configs/${documentId}/process-chunking/`,
            body
        );
    }

    stopChunkingByDocumentId(
        ragId: number,
        documentId: number,
        body: RunNaiveRagDocumentChunkingRequest
    ): Observable<CancelNaiveNaiveRagChunkingResponse> {
        return this.http.post<CancelNaiveNaiveRagChunkingResponse>(
            `${this.apiUrl}${ragId}/document-configs/${documentId}/process-chunking/cancel/`,
            body
        );
    }

    getChunkPreview(
        ragId: number,
        documentId: number,
        offset?: number,
        limit?: number
    ): Observable<GetNaiveRagDocumentChunksResponse> {
        let params = new HttpParams();

        if (offset !== undefined) {
            params = params.set('offset', offset.toString());
        }
        if (limit !== undefined) {
            params = params.set('limit', limit.toString());
        }

        return this.http.get<GetNaiveRagDocumentChunksResponse>(
            `${this.apiUrl}${ragId}/document-configs/${documentId}/chunks/`,
            { params }
        );
    }

    searchChunks(
        ragId: number,
        documentId: number,
        query: string,
        offset?: number,
        limit?: number
    ): Observable<ChunkSearchResponse> {
        let params = new HttpParams().set('q', query);

        if (offset !== undefined) {
            params = params.set('offset', offset.toString());
        }
        if (limit !== undefined) {
            params = params.set('limit', limit.toString());
        }

        return this.http.get<ChunkSearchResponse>(
            `${this.apiUrl}${ragId}/document-configs/${documentId}/chunks/search/`,
            { params }
        );
    }

    getChunksByIds(ragId: number, documentId: number, chunkIds: number[]): Observable<GetChunksByIdsResponse> {
        const dto = {
            preview_chunk_ids: chunkIds,
        };

        return this.http.post<GetChunksByIdsResponse>(
            `${this.apiUrl}${ragId}/document-configs/${documentId}/chunks/by-ids/`,
            dto
        );
    }
}
