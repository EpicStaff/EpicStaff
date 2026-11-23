import { HttpClient, HttpErrorResponse, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { forkJoin, map, Observable, retry, throwError, timer } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { GRAPH_VISUALIZATION_MAX_ENTITIES_PER_REQUEST } from '../constants/constants';
import {
    CollectionGraphRag,
    CreateGraphRagForCollectionResponse,
    CreateGraphRagIndexConfigRequest,
} from '../models/graph-rag.model';
import { GraphRagDocumentListResponse } from '../models/graph-rag-document.model';
import { GraphTableData, GraphTableSummaryItem, GraphVisualizationData } from '../models/graph-visualization.model';

/** Mirrors backend `GraphTableSearchScope`. `identity` narrows the `search` match to id + label columns. */
export type GraphTableSearchScope = 'all' | 'identity';

/** Options for `getTableData`. Only `ragId` and `tableName` are required; the rest default on the backend. */
export interface GetTableDataOptions {
    ragId: number;
    tableName: string;
    page?: number;
    pageSize?: number;
    search?: string;
    searchScope?: GraphTableSearchScope;
    filterColumn?: string;
    filterValue?: string;
    linkedToType?: string;
    linkedToId?: string;
}

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

    getTableData(options: GetTableDataOptions): Observable<GraphTableData> {
        const {
            ragId,
            tableName,
            page = 1,
            pageSize = 10,
            search,
            searchScope,
            filterColumn,
            filterValue,
            linkedToType,
            linkedToId,
        } = options;
        let params = new HttpParams().set('page', page.toString()).set('page_size', pageSize.toString());
        if (search) {
            params = params.set('search', search);
        }
        // Omit search_scope on the default so the request stays minimal; the backend treats a
        // missing param as `all`, matching the main table's any-column match behaviour.
        if (searchScope && searchScope !== 'all') {
            params = params.set('search_scope', searchScope);
        }
        // filter_column and filter_value go together — the backend rejects a partial pair with 400.
        // Both have to be non-empty strings: the backend treats an empty filter_value as a literal
        // empty-cell match, which is never what the UI wants.
        if (filterColumn && filterValue) {
            params = params.set('filter_column', filterColumn).set('filter_value', filterValue);
        }
        // linked_to_type and linked_to_id are a paired cross-table filter; the backend rejects a partial pair with 400.
        if (linkedToType && linkedToId) {
            params = params.set('linked_to_type', linkedToType).set('linked_to_id', linkedToId);
        }
        return this.http.get<GraphTableData>(`${this.apiUrl}${ragId}/tables/${tableName}/`, { params });
    }

    getTableSummary(ragId: number): Observable<GraphTableSummaryItem[]> {
        return this.http.get<GraphTableSummaryItem[]>(`${this.apiUrl}${ragId}/table-summary/`);
    }

    /**
     * Returns the allowed linked-to pairs as a dict keyed by subject-table name with the sorted list of
     * allowed target-table names. The response is a static per-service matrix with no per-rag variance,
     * so the URL carries no rag id. The server sets `Cache-Control: private, max-age=3600`, so the
     * browser reuses it within the hour.
     */
    getTableLinkPairs(): Observable<Record<string, string[]>> {
        return this.http.get<Record<string, string[]>>(`${this.apiUrl}table-link-pairs/`);
    }

    getVisualizationData(ragId: number, maxEntities?: number, search?: string): Observable<GraphVisualizationData> {
        // The backend caps a single visualization request at GRAPH_VISUALIZATION_MAX_ENTITIES_PER_REQUEST
        // entities. Larger totals are split across parallel requests that share the same top-N pool;
        // each request returns one page of entities and its share of the pool's edges. Backend handler:
        // src/knowledge_new/application/orchestrators/graph_visualization/strategies/graph.py.
        const perRequestCap = GRAPH_VISUALIZATION_MAX_ENTITIES_PER_REQUEST;
        if (maxEntities === undefined || maxEntities <= perRequestCap) {
            return this.requestVisualizationPage(ragId, maxEntities, search);
        }

        const total = maxEntities;
        const pageCount = Math.ceil(total / perRequestCap);
        const perPage = Math.ceil(total / pageCount);
        const pageRequests = Array.from({ length: pageCount }, (_, page) =>
            this.requestVisualizationPage(ragId, perPage, search, page, pageCount)
        );
        return forkJoin(pageRequests).pipe(map((pages) => this.mergeVisualizationPages(pages)));
    }

    private requestVisualizationPage(
        ragId: number,
        maxEntities: number | undefined,
        search: string | undefined,
        page?: number,
        pageCount?: number
    ): Observable<GraphVisualizationData> {
        let params = new HttpParams();
        if (maxEntities !== undefined) {
            params = params.set('max_entities', maxEntities.toString());
        }
        if (search) {
            params = params.set('search', search);
        }
        if (page !== undefined && pageCount !== undefined) {
            params = params.set('page', page.toString()).set('page_count', pageCount.toString());
        }
        // One retry per page with a short backoff for transient server/network failures: forkJoin
        // cancels siblings on the first error, so retrying a single 5XX saves the whole visualization.
        // 4XX are user-input errors — retrying wastes 300 ms before the real error surfaces.
        return this.http.get<GraphVisualizationData>(`${this.apiUrl}${ragId}/visualization/`, { params }).pipe(
            retry({
                count: 1,
                delay: (err) =>
                    err instanceof HttpErrorResponse && err.status >= 400 && err.status < 500
                        ? throwError(() => err)
                        : timer(300),
            })
        );
    }

    private mergeVisualizationPages(pages: GraphVisualizationData[]): GraphVisualizationData {
        if (pages.length === 0) {
            return { entities: [], relationships: [], total_entities: 0, total_relationships: 0 };
        }
        // Every page sees the same pool and reports its full-graph totals; take the max in case a
        // page was served from a replica that reported stale counts.
        return {
            entities: pages.flatMap((page) => page.entities),
            relationships: pages.flatMap((page) => page.relationships),
            total_entities: Math.max(...pages.map((page) => page.total_entities)),
            total_relationships: Math.max(...pages.map((page) => page.total_relationships)),
        };
    }

    getEntityDetails(ragId: number, entityId: string): Observable<{ description: string }> {
        return this.http.get<{ description: string }>(`${this.apiUrl}${ragId}/entity/${entityId}/`);
    }

    getRelationshipDetails(ragId: number, relationshipId: string): Observable<{ description: string }> {
        return this.http.get<{ description: string }>(`${this.apiUrl}${ragId}/relationship/${relationshipId}/`);
    }
}
