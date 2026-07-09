import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config/config.service';
import {
    AgentDefinition,
    CreateAgentDefinitionRequest,
    PartialUpdateAgentDefinitionRequest,
    UpdateAgentDefinitionRequest,
} from '../models/agent-definition.model';

@Injectable({ providedIn: 'root' })
export class AgentDefinitionsApiService {
    private readonly http: HttpClient = inject(HttpClient);
    private readonly configService: ConfigService = inject(ConfigService);

    private readonly httpHeaders = new HttpHeaders({ 'Content-Type': 'application/json' });

    private get baseUrl(): string {
        return `${this.configService.apiUrl}agent-definitions/`;
    }

    getAgentDefinitions(): Observable<AgentDefinition[]> {
        const params = new HttpParams().set('limit', '1000');
        return this.http.get<ApiGetRequest<AgentDefinition>>(this.baseUrl, { params }).pipe(map((res) => res.results));
    }

    getById(id: number): Observable<AgentDefinition> {
        return this.http.get<AgentDefinition>(`${this.baseUrl}${id}/`, { headers: this.httpHeaders });
    }

    create(body: CreateAgentDefinitionRequest): Observable<AgentDefinition> {
        return this.http.post<AgentDefinition>(this.baseUrl, body, { headers: this.httpHeaders });
    }

    update(id: number, body: UpdateAgentDefinitionRequest): Observable<AgentDefinition> {
        return this.http.put<AgentDefinition>(`${this.baseUrl}${id}/`, body, { headers: this.httpHeaders });
    }

    partialUpdate(id: number, body: PartialUpdateAgentDefinitionRequest): Observable<AgentDefinition> {
        return this.http.patch<AgentDefinition>(`${this.baseUrl}${id}/`, body, { headers: this.httpHeaders });
    }

    delete(id: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${id}/`, { headers: this.httpHeaders });
    }

    // no backend "copy" endpoint. Client-side: clone fields + new name.
    copy(source: AgentDefinition, newName: string): Observable<AgentDefinition> {
        const body: CreateAgentDefinitionRequest = {
            name: newName,
            instructions: source.instructions,
            description: source.description,
            llm_config: source.llm_config,
            fcm_llm_config: source.fcm_llm_config,
            default_surfaces: source.default_surfaces,
            metadata: source.metadata,
            max_iter: source.max_iter,
            max_rpm: source.max_rpm,
            max_execution_time: source.max_execution_time,
            cache: source.cache,
            max_retry_limit: source.max_retry_limit,
            default_temperature: source.default_temperature,
            max_tool_calls: source.max_tool_calls,
            tool_timeout: source.tool_timeout,
            max_consecutive_failures: source.max_consecutive_failures,
        };
        return this.create(body);
    }
}
