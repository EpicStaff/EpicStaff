import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config/config.service';
import {
    CreateGraphDtoRequest,
    GetGraphLightRequest,
    GraphDto,
    GraphVersionCreateRequest,
    GraphVersionDto,
    UpdateGraphDtoRequest,
} from '../models/graph.model';

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
            .get<ApiGetRequest<GraphDto>>(this.apiUrl)
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
        return this.http
            .get<
                ApiGetRequest<GetGraphLightRequest>
            >(`${this.configService.apiUrl}graph-light/`, { params: httpParams })
            .pipe(map((response) => response.results.sort((a, b) => b.id - a.id)));
    }

    getEpicChatEnabledFlows(): Observable<GraphDto[]> {
        const params = new HttpParams().set('epicchat_enabled', 'true');
        return this.http
            .get<ApiGetRequest<GraphDto>>(`${this.configService.apiUrl}graph-light/`, { params })
            .pipe(map((response) => response.results));
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
}
