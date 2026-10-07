import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { forkJoin, Observable, of } from 'rxjs';
import { map, switchMap } from 'rxjs/operators';

import { withPermission } from '../../../core/http/permission-context';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';
import { GetScheduleTriggerNodeRequest } from '../../../visual-programming/core/models/schedule-trigger.model';
import {
    CreateGraphDtoRequest,
    CreateGraphFromVersionResponse,
    GetGraphLightRequest,
    GraphDto,
    GraphRestoreResponse,
    GraphVersionCreateRequest,
    GraphVersionDto,
    GraphVersionUpdateRequest,
    UpdateGraphDtoRequest,
} from '../models/graph.model';
import { PreviewGraphVersionResponse } from '../models/graph-version-preview.model';

@Injectable({
    providedIn: 'root',
})
export class FlowsApiService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    private readonly httpHeaders = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    private get apiUrl(): string {
        return `${this.configService.apiUrl}graphs/`;
    }

    getGraphs(): Observable<GraphDto[]> {
        return this.http
            .get<ApiGetRequest<GraphDto>>(this.apiUrl, {
                context: withPermission<ApiGetRequest<GraphDto>>(ResourceCode.Flows, ActionCode.Read, {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                }),
            })
            .pipe(map((response) => response.results.sort((a, b) => b.id - a.id)));
    }

    getGraphsLight(params?: { label_id?: number; no_label?: boolean }): Observable<GetGraphLightRequest[]> {
        let httpParams = new HttpParams();
        if (params?.label_id !== undefined) {
            httpParams = httpParams.set('label_id', params.label_id.toString());
        }
        if (params?.no_label) {
            httpParams = httpParams.set('no_label', 'true');
        }
        return this.getAllFlowPages<GetGraphLightRequest>(`${this.configService.apiUrl}graph-light/`, httpParams).pipe(
            map((results) => results.sort((a, b) => b.id - a.id))
        );
    }

    getEpicChatEnabledFlows(): Observable<GraphDto[]> {
        const params = new HttpParams().set('epicchat_enabled', 'true');
        return this.getAllFlowPages<GraphDto>(`${this.configService.apiUrl}graph-light/`, params);
    }

    getGraphById(id: number, forceRefresh = false): Observable<GraphDto> {
        const params = forceRefresh ? new HttpParams().set('_ts', Date.now().toString()) : undefined;
        return this.http.get<GraphDto>(`${this.apiUrl}${id}/`, { params });
    }

    createGraph(graph: CreateGraphDtoRequest): Observable<GraphDto> {
        return this.http.post<GraphDto>(this.apiUrl, graph, {
            headers: this.httpHeaders,
        });
    }

    updateGraph(id: number, graph: UpdateGraphDtoRequest): Observable<GraphDto> {
        return this.http.put<GraphDto>(`${this.apiUrl}${id}/`, graph, {
            headers: this.httpHeaders,
        });
    }

    patchGraph(id: number, fields: Partial<GraphDto>): Observable<GraphDto> {
        return this.http.patch<GraphDto>(`${this.apiUrl}${id}/`, fields, {
            headers: this.httpHeaders,
        });
    }

    bulkSaveGraph(graphId: number, payload: Record<string, unknown>): Observable<GraphDto> {
        return this.http.post<GraphDto>(`${this.apiUrl}${graphId}/save/`, payload, {
            headers: this.httpHeaders,
        });
    }

    deleteGraph(id: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`);
    }

    copyGraph(id: number, name: string): Observable<GraphDto> {
        return this.http.post<GraphDto>(
            `${this.apiUrl}${id}/copy/`,
            { name },
            {
                headers: this.httpHeaders,
            }
        );
    }

    getGraphStatus(runId: string): Observable<Record<string, unknown>> {
        return this.http.get<Record<string, unknown>>(`${this.configService.apiUrl}graph_runs/${runId}/status/`);
    }

    saveGraphVersion(payload: GraphVersionCreateRequest): Observable<GraphVersionDto> {
        return this.http.post<GraphVersionDto>(`${this.configService.apiUrl}graph-versions/`, payload, {
            headers: this.httpHeaders,
        });
    }

    getGraphVersions(graphId: number): Observable<GraphVersionDto[]> {
        const params = new HttpParams().set('graph_id', graphId.toString());
        return this.http
            .get<ApiGetRequest<GraphVersionDto>>(`${this.configService.apiUrl}graph-versions/`, { params })
            .pipe(map((response) => response.results));
    }

    updateGraphVersion(id: number, data: GraphVersionUpdateRequest): Observable<GraphVersionDto> {
        return this.http.patch<GraphVersionDto>(`${this.configService.apiUrl}graph-versions/${id}/`, data, {
            headers: this.httpHeaders,
        });
    }

    restoreGraphVersion(id: number, backup = true, saveVersion?: number): Observable<GraphRestoreResponse> {
        const params = backup ? new HttpParams().set('backup', 'true') : undefined;
        const body = saveVersion !== undefined ? { save_version: saveVersion } : {};
        return this.http.post<GraphRestoreResponse>(`${this.configService.apiUrl}graph-versions/${id}/restore/`, body, {
            headers: this.httpHeaders,
            params,
        });
    }

    deleteGraphVersion(id: number): Observable<void> {
        return this.http.delete<void>(`${this.configService.apiUrl}graph-versions/${id}/`);
    }

    getScheduleTriggerNode(id: number): Observable<GetScheduleTriggerNodeRequest> {
        return this.http.get<GetScheduleTriggerNodeRequest>(
            `${this.configService.apiUrl}schedule-trigger-nodes/${id}/`
        );
    }

    createGraphFromVersion(versionId: number): Observable<CreateGraphFromVersionResponse> {
        return this.http.post<CreateGraphFromVersionResponse>(
            `${this.configService.apiUrl}graph-versions/${versionId}/create-graph/`,
            {},
            { headers: this.httpHeaders }
        );
    }

    previewGraphVersion(versionId: number): Observable<PreviewGraphVersionResponse> {
        return this.http.get<PreviewGraphVersionResponse>(
            `${this.configService.apiUrl}graph-versions/${versionId}/preview/`
        );
    }

    getSubflowUsage(graphId: number): Observable<{ parent_flow_ids: number[] }> {
        return this.http.get<{ parent_flow_ids: number[] }>(`${this.apiUrl}${graphId}/subflow-usage/`);
    }

    /** Loads every page of a paginated flows list: the first page, then all remaining pages in parallel.
     *  Only the query string of `next` is used: its host and scheme come from the proxy-forwarded
     *  headers and can be wrong, so every page is requested at the original `url`. */
    private getAllFlowPages<T extends { id: number }>(url: string, params: HttpParams): Observable<T[]> {
        return this.getFlowPage<T>(url, params).pipe(
            switchMap((firstPage) => {
                if (!firstPage.next) {
                    return of(firstPage.results);
                }
                const nextPageParams = this.getQueryParams(firstPage.next);
                const pageSize = Number(nextPageParams.get('limit')) || firstPage.results.length;
                const remainingPages: Observable<ApiGetRequest<T>>[] = [];
                if (pageSize > 0) {
                    for (let offset = pageSize; offset < firstPage.count; offset += pageSize) {
                        remainingPages.push(this.getFlowPage<T>(url, nextPageParams.set('offset', offset.toString())));
                    }
                }
                if (remainingPages.length === 0) {
                    return of(firstPage.results);
                }
                return forkJoin(remainingPages).pipe(map((pages) => this.mergeUniqueById([firstPage, ...pages])));
            })
        );
    }

    /** Rows can shift between pages when a flow is created or deleted mid-fetch; the first occurrence wins. */
    private mergeUniqueById<T extends { id: number }>(pages: ApiGetRequest<T>[]): T[] {
        const seenIds = new Set<number>();
        return pages
            .flatMap((page) => page.results)
            .filter((item) => {
                if (seenIds.has(item.id)) {
                    return false;
                }
                seenIds.add(item.id);
                return true;
            });
    }

    private getQueryParams(pageUrl: string): HttpParams {
        const queryString = new URL(pageUrl, window.location.origin).search.substring(1);
        return new HttpParams({ fromString: queryString });
    }

    private getFlowPage<T>(url: string, params?: HttpParams): Observable<ApiGetRequest<T>> {
        return this.http.get<ApiGetRequest<T>>(url, {
            params,
            context: withPermission<ApiGetRequest<T>>(ResourceCode.Flows, ActionCode.Read, {
                count: 0,
                next: null,
                previous: null,
                results: [],
            }),
        });
    }
}
