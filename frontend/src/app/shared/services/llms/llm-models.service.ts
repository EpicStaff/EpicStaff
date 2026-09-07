import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { ActionCode, CreateLlmModelRequest, LLMModel, ResourceCode } from '@shared/models';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { withPermission } from '../../../core/http/permission-context';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';

@Injectable({
    providedIn: 'root',
})
export class LLMModelsService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'llm-models/';
    }

    getLLMModels(providerId?: number, isVisible?: boolean): Observable<LLMModel[]> {
        let params = new HttpParams().set('limit', '1000');

        if (providerId) {
            params = params.set('llm_provider', providerId.toString());
        }

        if (isVisible !== undefined) {
            params = params.set('is_visible', isVisible.toString());
        }

        return this.http
            .get<ApiGetRequest<LLMModel>>(this.apiUrl, {
                headers: this.headers,
                params,
                context: withPermission<ApiGetRequest<LLMModel>>(ResourceCode.LlmConfigs, ActionCode.Read, {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                }),
            })
            .pipe(map((response) => response.results));
    }

    getLLMModelById(id: number): Observable<LLMModel> {
        return this.http.get<LLMModel>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }

    updateModel(id: number, data: Partial<LLMModel>): Observable<LLMModel> {
        return this.http.put<LLMModel>(`${this.apiUrl}${id}/`, data, {
            headers: this.headers,
        });
    }

    patchModel(id: number, data: Partial<LLMModel>): Observable<LLMModel> {
        return this.http.patch<LLMModel>(`${this.apiUrl}${id}/`, data, {
            headers: this.headers,
        });
    }

    createModel(data: CreateLlmModelRequest): Observable<LLMModel> {
        return this.http.post<LLMModel>(this.apiUrl, data, {
            headers: this.headers,
        });
    }

    deleteModel(id: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }
}
