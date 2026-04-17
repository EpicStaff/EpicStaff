import { HttpClient, HttpHeaders } from "@angular/common/http";
import { inject, Injectable } from "@angular/core";
import { Observable } from "rxjs";
import { ConfigService } from "../../../services/config";
import { StartIndexingDtoRequest, StartIndexingDtoResponse } from "../models/base-rag.model";
import {
    CollectionGraphRag,
    CreateGraphRagForCollectionResponse, CreateGraphRagIndexConfigRequest,
} from "../models/graph-rag.model";

@Injectable({
    providedIn: 'root'
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
        llmId: number,
    ): Observable<CreateGraphRagForCollectionResponse> {
        const body = { embedder_id: embedderId, llm_id: llmId };

        return this.http.post<CreateGraphRagForCollectionResponse>(
            `${this.apiUrl}collections/${collectionId}/graph-rag/`,
            body
        )
    }

    getRagById(ragId: number): Observable<CollectionGraphRag> {
        return this.http.get<CollectionGraphRag>(`${this.apiUrl}${ragId}/`)
    }

    updateRagIndexConfigs(ragId: number, dto: CreateGraphRagIndexConfigRequest): Observable<CreateGraphRagIndexConfigRequest> {
        return this.http.put<CreateGraphRagIndexConfigRequest>(
            `${this.apiUrl}${ragId}/index-config/`,
            dto
        )
    }

    startIndexing(dto: StartIndexingDtoRequest): Observable<StartIndexingDtoResponse> {
        return this.http.post<StartIndexingDtoResponse>(`${this.configService.apiUrl}process-rag-indexing/`, dto)
    }

    deleteFileById(ragId: number, fileId: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${ragId}/documents/${fileId}/`);
    }

    reIncludeFiles(ragId: number): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}${ragId}/documents/initialize/`, {});
    }
}
