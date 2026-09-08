import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { finalize, map, Observable, shareReplay } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config/config.service';
import {
    GraphSuggestRequest,
    NaiveSuggestRequest,
    SuggestResponse,
} from '../../../shared/models/agent-search-config.model';
import {
    CreateAgentRequest,
    GetAgentRequest,
    PartialUpdateAgentRequest,
    UpdateAgentRequest,
} from '../models/agent.model';

@Injectable({
    providedIn: 'root',
})
export class AgentsService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    // Dynamically retrieve the API URL from ConfigService
    private get apiUrl(): string {
        return this.configService.apiUrl + 'agents/';
    }

    // GET all agents
    getAgents(): Observable<GetAgentRequest[]> {
        const url = this.apiUrl;
        return this.http.get<ApiGetRequest<GetAgentRequest>>(url).pipe(map((response) => response.results));
    }

    // GET agents that have a realtime config configured
    getAgentsWithRealtimeConfig(): Observable<GetAgentRequest[]> {
        return this.http
            .get<ApiGetRequest<GetAgentRequest>>(`${this.apiUrl}?has_realtime_config=true`)
            .pipe(map((response) => response.results));
    }

    // GET agents by project (crew) ID
    getAgentsByProjectId(projectId: number): Observable<GetAgentRequest[]> {
        const url = `${this.apiUrl}?crew_id=${projectId}`;
        return this.http.get<ApiGetRequest<GetAgentRequest>>(url).pipe(map((response) => response.results));
    }

    getAgentById(agentId: number): Observable<GetAgentRequest> {
        return this.http.get<GetAgentRequest>(`${this.apiUrl}${agentId}/`);
    }

    // POST create agent
    createAgent(agent: CreateAgentRequest): Observable<GetAgentRequest> {
        return this.http.post<GetAgentRequest>(this.apiUrl, agent, {
            headers: this.headers,
        });
    }

    // PATCH update agent
    partialUpdateAgent(agent: PartialUpdateAgentRequest): Observable<PartialUpdateAgentRequest> {
        return this.http.patch<PartialUpdateAgentRequest>(`${this.apiUrl}${agent.id}/`, agent, {
            headers: this.headers,
        });
    }

    // PUT update agent
    updateAgent(agent: UpdateAgentRequest): Observable<UpdateAgentRequest> {
        return this.http.put<UpdateAgentRequest>(`${this.apiUrl}${agent.id}/`, agent, {
            headers: this.headers,
        });
    }

    // DELETE agent
    deleteAgent(agentId: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${agentId}/`, {
            headers: this.headers,
        });
    }

    // COPY agent
    copyAgent(agent: CreateAgentRequest, agentId: number): Observable<GetAgentRequest> {
        return this.http.post<GetAgentRequest>(`${this.apiUrl}${agentId}/copy/`, agent, {
            headers: this.headers,
        });
    }

    // In-flight suggest-search-params requests, keyed by their exact params.
    // Whatever triggers a duplicate call (two component instances, a re-fired
    // effect, a double-click reopening the dialog, etc.), this guarantees only
    // one actual HTTP request is ever in flight for the same params — every
    // caller during that window shares the same response instead of the
    // backend seeing two identical requests.
    private inFlightNaiveSuggest = new Map<string, Observable<SuggestResponse>>();
    private inFlightGraphSuggest = new Map<string, Observable<SuggestResponse>>();

    // POST suggest search params for naive RAG
    suggestNaiveSearchParams(body: NaiveSuggestRequest): Observable<SuggestResponse> {
        const key = `${body.knowledge_collection_id}|${body.llm_config_id}|${JSON.stringify(body.user_custom_params ?? null)}`;
        const existing = this.inFlightNaiveSuggest.get(key);
        if (existing) return existing;

        const url = `${this.configService.apiUrl}naive-rag/suggest-search-params/`;
        const request$ = this.http.post<SuggestResponse>(url, body, { headers: this.headers }).pipe(
            finalize(() => this.inFlightNaiveSuggest.delete(key)),
            shareReplay(1)
        );
        this.inFlightNaiveSuggest.set(key, request$);
        return request$;
    }

    // POST suggest search params for graph RAG
    suggestGraphSearchParams(body: GraphSuggestRequest): Observable<SuggestResponse> {
        const key = `${body.knowledge_collection_id}|${body.llm_config_id}|${body.search_method}|${JSON.stringify(body.user_custom_params ?? null)}`;
        const existing = this.inFlightGraphSuggest.get(key);
        if (existing) return existing;

        const url = `${this.configService.apiUrl}graph-rag/suggest-search-params/`;
        const request$ = this.http.post<SuggestResponse>(url, body, { headers: this.headers }).pipe(
            finalize(() => this.inFlightGraphSuggest.delete(key)),
            shareReplay(1)
        );
        this.inFlightGraphSuggest.set(key, request$);
        return request$;
    }
}
