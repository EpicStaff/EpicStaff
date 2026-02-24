import { inject, Injectable } from "@angular/core";
import { HttpClient, HttpHeaders, HttpParams } from "@angular/common/http";
import { ConfigService } from "../../../services/config";
import { Observable } from "rxjs";
import { GetNaiveRagDocumentChunksResponse, NaiveRagChunkingResponse } from "../models/naive-rag-chunk.model";
import {
    BulkDeleteNaiveRagDocumentDtoRequest,
    BulkDeleteNaiveRagDocumentDtoResponse,
    BulkUpdateNaiveRagDocumentDtoRequest,
    BulkUpdateNaiveRagDocumentDtoResponse,
    GetNaiveRagDocumentConfigsResponse,
    InitNaiveRagDocumentsResponse,
    StartIndexingDtoRequest,
    StartIndexingDtoResponse,
    UpdateNaiveRagDocumentDtoRequest,
    UpdateNaiveRagDocumentResponse
} from "../models/naive-rag-document.model";
import {
    CreateRagForCollectionResponse
} from "../models/naive-rag.model";

@Injectable({
    providedIn: 'root'
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

    createRagForCollection(
        collectionId: number,
        embedderId: number
    ): Observable<CreateRagForCollectionResponse> {
        const body = { embedder_id: embedderId };

        return this.http.post<CreateRagForCollectionResponse>(
            `${this.apiUrl}collections/${collectionId}/naive-rag/`,
            body
        )
    }

    getDocumentConfigs(naiveRagId: number): Observable<GetNaiveRagDocumentConfigsResponse> {
        return this.http.get<GetNaiveRagDocumentConfigsResponse>(`${this.apiUrl}${naiveRagId}/document-configs/`);
    }

    updateDocumentConfigById(
        ragId: number,
        documentId: number,
        dto: UpdateNaiveRagDocumentDtoRequest
    ): Observable<UpdateNaiveRagDocumentResponse> {
        return this.http.put<UpdateNaiveRagDocumentResponse>(
            `${this.apiUrl}${ragId}/document-configs/${documentId}/`,
            dto
        );
    }

    bulkUpdateDocumentConfigs(
        ragId: number,
        dto: BulkUpdateNaiveRagDocumentDtoRequest
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

    startIndexing(dto: StartIndexingDtoRequest): Observable<StartIndexingDtoResponse> {
        return this.http.post<StartIndexingDtoResponse>(`${this.configService.apiUrl}process-rag-indexing/`, dto)
    }

    initializeDocuments(ragId: number): Observable<InitNaiveRagDocumentsResponse> {
        return this.http.post<InitNaiveRagDocumentsResponse>(
            `${this.apiUrl}${ragId}/document-configs/initialize/`,
            {}
        );
    }

    runChunkingProcess(ragId: number, documentId: number): Observable<NaiveRagChunkingResponse> {
        return this.http.post<NaiveRagChunkingResponse>(
            `${this.apiUrl}${ragId}/document-configs/${documentId}/process-chunking/`,
            {}
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
}
