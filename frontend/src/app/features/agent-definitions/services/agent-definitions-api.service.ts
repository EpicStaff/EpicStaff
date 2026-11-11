import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { ActionCode, ExportResult, ResourceCode } from '@shared/models';
import { toExportResult } from '@shared/utils';
import { map, Observable, tap } from 'rxjs';

import { withPermission } from '../../../core/http/permission-context';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import { InspectResult } from '../../../core/models/review-item.model';
import { ConfigService } from '../../../services/config';
import {
    AgentDefinition,
    CreateAgentDefinitionRequest,
    PartialUpdateAgentDefinitionRequest,
} from '../models/agent-definition.model';

@Injectable({ providedIn: 'root' })
export class AgentDefinitionsApiService {
    private readonly http: HttpClient = inject(HttpClient);
    private readonly configService: ConfigService = inject(ConfigService);

    private readonly httpHeaders = new HttpHeaders({ 'Content-Type': 'application/json' });

    private readonly definitionsSignal = signal<AgentDefinition[]>([]);
    public readonly definitions = this.definitionsSignal.asReadonly();

    private get baseUrl(): string {
        return `${this.configService.apiUrl}agent-definitions/`;
    }

    getAgentDefinitions(): Observable<AgentDefinition[]> {
        const params = new HttpParams().set('limit', '1000');
        return this.http
            .get<ApiGetRequest<AgentDefinition>>(this.baseUrl, {
                params,
                context: withPermission<ApiGetRequest<AgentDefinition>>(ResourceCode.Agents, ActionCode.Read, {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                }),
            })
            .pipe(map((res) => res.results));
    }

    /** Fetches agent definitions fresh and publishes them into the shared `definitions` signal. */
    refreshDefinitions(): Observable<AgentDefinition[]> {
        return this.getAgentDefinitions().pipe(tap((defs) => this.definitionsSignal.set(defs)));
    }

    getById(id: number): Observable<AgentDefinition> {
        return this.http.get<AgentDefinition>(`${this.baseUrl}${id}/`, { headers: this.httpHeaders });
    }

    create(body: CreateAgentDefinitionRequest): Observable<AgentDefinition> {
        return this.http.post<AgentDefinition>(this.baseUrl, body, { headers: this.httpHeaders });
    }

    partialUpdate(id: number, body: PartialUpdateAgentDefinitionRequest): Observable<AgentDefinition> {
        return this.http.patch<AgentDefinition>(`${this.baseUrl}${id}/`, body, { headers: this.httpHeaders });
    }

    delete(id: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${id}/`, { headers: this.httpHeaders });
    }

    exportAgent(id: number): Observable<ExportResult> {
        return this.http
            .get(`${this.baseUrl}${id}/export/`, { observe: 'response', responseType: 'blob' })
            .pipe(map(toExportResult));
    }

    bulkExportAgents(ids: number[]): Observable<ExportResult> {
        return this.http
            .post(`${this.baseUrl}bulk-export/`, { ids }, { observe: 'response', responseType: 'blob' })
            .pipe(map(toExportResult));
    }

    inspectImport(file: File): Observable<InspectResult> {
        const form = new FormData();
        form.append('file', file);
        return this.http.post<InspectResult>(`${this.baseUrl}import/inspect/`, form);
    }

    importAgents(file: File, importLabels = true): Observable<Record<string, unknown>> {
        const form = new FormData();
        form.append('file', file);
        form.append('import_labels', String(importLabels));
        return this.http.post<Record<string, unknown>>(`${this.baseUrl}import/`, form);
    }

    /** The server clones the agent with its owned surfaces and names the copy ("X #2", "X #3", ...). */
    copy(id: number): Observable<AgentDefinition> {
        return this.http.post<AgentDefinition>(`${this.baseUrl}${id}/copy/`, {}, { headers: this.httpHeaders });
    }
}
