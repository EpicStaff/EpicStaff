import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import {
    ActionCode,
    CreateLLMConfigRequest,
    GetLlmConfigRequest,
    ResourceCode,
    UpdateLLMConfigRequest,
} from '@shared/models';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { withPermission } from '../../../core/http/permission-context';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';

@Injectable({
    providedIn: 'root',
})
export class LLMConfigService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'llm-configs/';
    }

    getAllConfigsLLM(): Observable<GetLlmConfigRequest[]> {
        const params = new HttpParams().set('limit', '1000');

        return this.http
            .get<ApiGetRequest<GetLlmConfigRequest>>(this.apiUrl, {
                headers: this.headers,
                params,
                context: withPermission<ApiGetRequest<GetLlmConfigRequest>>(ResourceCode.LlmConfigs, ActionCode.Read, {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                }),
            })
            .pipe(map((response) => response.results));
    }

    getConfigsByProviderId(providerId: number): Observable<GetLlmConfigRequest[]> {
        const params = new HttpParams().set('model_provider_id', providerId.toString()).set('limit', '1000');

        return this.http
            .get<ApiGetRequest<GetLlmConfigRequest>>(this.apiUrl, {
                headers: this.headers,
                params,
            })
            .pipe(map((response) => response.results));
    }

    getConfigById(id: number): Observable<GetLlmConfigRequest> {
        return this.http.get<GetLlmConfigRequest>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }

    createConfig(configData: CreateLLMConfigRequest): Observable<GetLlmConfigRequest> {
        return this.http.post<GetLlmConfigRequest>(this.apiUrl, configData, {
            headers: this.headers,
        });
    }

    updateConfig(configData: UpdateLLMConfigRequest): Observable<GetLlmConfigRequest> {
        return this.http.put<GetLlmConfigRequest>(`${this.apiUrl}${configData.id}/`, configData, {
            headers: this.headers,
        });
    }

    deleteConfig(id: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }
}
