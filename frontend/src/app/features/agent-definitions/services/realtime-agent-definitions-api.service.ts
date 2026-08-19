import { HttpClient, HttpErrorResponse, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { catchError, map, Observable, of, throwError } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config/config.service';
import {
    CreateRealtimeAgentDefinitionRequest,
    PartialUpdateRealtimeAgentDefinitionRequest,
    RealtimeAgentDefinition,
} from '../models/realtime-agent-definition.model';

@Injectable({ providedIn: 'root' })
export class RealtimeAgentDefinitionsApiService {
    private readonly http: HttpClient = inject(HttpClient);
    private readonly configService: ConfigService = inject(ConfigService);

    private readonly httpHeaders = new HttpHeaders({ 'Content-Type': 'application/json' });

    private get baseUrl(): string {
        return `${this.configService.apiUrl}realtime-agent-definitions/`;
    }

    list(): Observable<RealtimeAgentDefinition[]> {
        const params = new HttpParams().set('limit', '1000');
        return this.http
            .get<ApiGetRequest<RealtimeAgentDefinition>>(this.baseUrl, { headers: this.httpHeaders, params })
            .pipe(
                map((res) => {
                    // Single-page fetch (matches getAgentDefinitions). Warn instead of silently
                    // dropping rows if an org ever exceeds the cap.
                    if (res.count > res.results.length) {
                        console.warn(
                            `RealtimeAgentDefinitions: ${res.count} rows but only ${res.results.length} fetched — increase limit or paginate.`
                        );
                    }
                    return res.results;
                })
            );
    }

    // Detail pk = agent definition id (OneToOne). 404 = no row = voice off → null.
    // Other errors (403/500/…) are surfaced so callers don't mistake them for "voice off".
    getByAgentId(agentId: number): Observable<RealtimeAgentDefinition | null> {
        return this.http
            .get<RealtimeAgentDefinition>(`${this.baseUrl}${agentId}/`, { headers: this.httpHeaders })
            .pipe(catchError((err: HttpErrorResponse) => (err.status === 404 ? of(null) : throwError(() => err))));
    }

    create(body: CreateRealtimeAgentDefinitionRequest): Observable<RealtimeAgentDefinition> {
        return this.http.post<RealtimeAgentDefinition>(this.baseUrl, body, { headers: this.httpHeaders });
    }

    partialUpdate(
        agentId: number,
        body: PartialUpdateRealtimeAgentDefinitionRequest
    ): Observable<RealtimeAgentDefinition> {
        return this.http.patch<RealtimeAgentDefinition>(`${this.baseUrl}${agentId}/`, body, {
            headers: this.httpHeaders,
        });
    }

    delete(agentId: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${agentId}/`, { headers: this.httpHeaders });
    }
}
